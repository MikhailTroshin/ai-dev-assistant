import asyncio
import json
import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import redis.asyncio as redis
from arq import create_pool
from arq.connections import RedisSettings

from config.settings import settings

logger = logging.getLogger(__name__)

router = Router()


class AskStates(StatesGroup):
    waiting_for_question = State()


class TaskStates(StatesGroup):
    waiting_for_task_key = State()


class BugStates(StatesGroup):
    waiting_for_logs = State()


def split_message(text: str, max_length: int = 4000) -> list[str]:
    """Разбивает длинное сообщение на части"""
    if len(text) <= max_length:
        return [text]
    
    parts = []
    while text:
        if len(text) <= max_length:
            parts.append(text)
            break
        
        # Ищем последнее место для разреза (по параграфам или предложениям)
        split_pos = text.rfind('\n\n', 0, max_length)
        if split_pos == -1:
            split_pos = text.rfind('\n', 0, max_length)
        if split_pos == -1:
            split_pos = text.rfind('. ', 0, max_length)
        if split_pos == -1:
            split_pos = max_length
        
        parts.append(text[:split_pos])
        text = text[split_pos:].lstrip()
    
    return parts


async def send_long_message(message: Message, text: str):
    """Отправляет длинное сообщение, разбивая на части"""
    parts = split_message(text)
    for i, part in enumerate(parts, 1):
        if len(parts) > 1:
            await message.answer(f"📄 Часть {i}/{len(parts)}:\n\n{part}")
        else:
            await message.answer(part)
        await asyncio.sleep(0.5)  # Небольшая пауза между сообщениями


@router.message(Command("start"))
async def cmd_start(message: Message):
    text = """
👋 Привет! Я AI-ассистент для работы с проектом.

Доступные команды:
/ask - Задать вопрос по проекту
/task - Взять задачу из Jira
/bug - Проанализировать баг по логам
/status - Статус системы

⏱ Длинные задачи выполняются асинхронно - я сообщу, когда будет готово!
"""
    await message.answer(text)


@router.message(Command("ask"))
async def cmd_ask(message: Message, state: FSMContext):
    await state.set_state(AskStates.waiting_for_question)
    await message.answer("📝 Напиши свой вопрос по проекту:")


@router.message(AskStates.waiting_for_question)
async def process_question(message: Message, state: FSMContext, redis_pool, bot):
    question = message.text
    
    if not question:
        await message.answer("❌ Вопрос не может быть пустым")
        await state.clear()
        return
    
    task_id = f"ask_{message.from_user.id}_{message.message_id}"
    
    await message.answer(
        f"⏳ Задача принята!\n"
        f"ID: `{task_id}`\n\n"
        f"Сообщу, когда будет готово (может занять до 10 минут)",
        parse_mode="Markdown"
    )
    
    # Добавляем задачу в очередь
    await redis_pool.enqueue_job(
        'process_task',
        task_id=task_id,
        prompt=f"Ответь на вопрос по проекту: {question}",
        working_dir=str(settings.ML_REPO_PATH),
        chat_id=message.chat.id,
        user_id=message.from_user.id
    )
    
    # Сохраняем связь task_id → chat_id для отправки результата
    redis_client = redis.from_url(
        f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
    )
    await redis_client.hset(
        "task_chat_mapping",
        task_id,
        json.dumps({"chat_id": message.chat.id, "user_id": message.from_user.id})
    )
    await redis_client.close()
    
    await state.clear()


@router.message(Command("task"))
async def cmd_task(message: Message, state: FSMContext):
    await state.set_state(TaskStates.waiting_for_task_key)
    await message.answer("📋 Введи ключ задачи из Jira (например, PROJ-123):")


@router.message(TaskStates.waiting_for_task_key)
async def process_task_key(message: Message, state: FSMContext, redis_pool, bot):
    task_key = message.text.strip().upper()
    
    if not task_key or '-' not in task_key:
        await message.answer("❌ Неверный формат ключа задачи")
        await state.clear()
        return
    
    task_id = f"task_{message.from_user.id}_{message.message_id}"
    
    await message.answer(
        f"⏳ Задача принята!\n"
        f"ID: `{task_id}`\n\n"
        f"Получаю информацию о задаче {task_key}...",
        parse_mode="Markdown"
    )
    
    await redis_pool.enqueue_job(
        'process_task',
        task_id=task_id,
        prompt=f"Прочитай задачу {task_key} из Jira и покажи её описание, требования и критерии приёмки",
        working_dir=str(settings.ML_REPO_PATH),
        chat_id=message.chat.id,
        user_id=message.from_user.id
    )
    
    redis_client = redis.from_url(
        f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
    )
    await redis_client.hset(
        "task_chat_mapping",
        task_id,
        json.dumps({"chat_id": message.chat.id, "user_id": message.from_user.id})
    )
    await redis_client.close()
    
    await state.clear()


@router.message(Command("bug"))
async def cmd_bug(message: Message, state: FSMContext):
    await state.set_state(BugStates.waiting_for_logs)
    await message.answer("🐛 Отправь лог-файл или текст с описанием бага:")


@router.message(BugStates.waiting_for_logs, F.text)
async def process_bug_text(message: Message, state: FSMContext, redis_pool, bot):
    bug_description = message.text
    task_id = f"bug_{message.from_user.id}_{message.message_id}"
    
    await message.answer(
        f"⏳ Задача принята!\n"
        f"ID: `{task_id}`\n\n"
        f"Анализирую баг...",
        parse_mode="Markdown"
    )
    
    await redis_pool.enqueue_job(
        'process_task',
        task_id=task_id,
        prompt=f"Проанализируй этот баг и найди возможные причины в коде:\n\n{bug_description}",
        working_dir=str(settings.ML_REPO_PATH),
        chat_id=message.chat.id,
        user_id=message.from_user.id
    )
    
    redis_client = redis.from_url(
        f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
    )
    await redis_client.hset(
        "task_chat_mapping",
        task_id,
        json.dumps({"chat_id": message.chat.id, "user_id": message.from_user.id})
    )
    await redis_client.close()
    
    await state.clear()


@router.message(Command("status"))
async def cmd_status(message: Message, redis_pool):
    redis_info = await redis_pool.info()
    
    # Проверяем количество ожидающих результатов
    redis_client = redis.from_url(
        f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
    )
    pending_count = await redis_client.scard("pending_results")
    await redis_client.close()
    
    text = f"""
📊 Статус системы:

Redis:
- Подключений: {redis_info.get('connected_clients', 'N/A')}
- Используется памяти: {redis_info.get('used_memory_human', 'N/A')}

Задачи:
- Ожидают отправки: {pending_count}

Система работает ✅
"""
    await message.answer(text)
    