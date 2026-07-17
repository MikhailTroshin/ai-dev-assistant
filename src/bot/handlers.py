import asyncio
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from arq import create_pool
from arq.connections import RedisSettings

from config.settings import settings

logger = logging.getLogger(__name__)

router = Router()


class AskStates(StatesGroup):
    """Состояния для команды /ask"""
    waiting_for_question = State()


class TaskStates(StatesGroup):
    """Состояния для команды /task"""
    waiting_for_task_key = State()


class BugStates(StatesGroup):
    """Состояния для команды /bug"""
    waiting_for_logs = State()


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    text = """
👋 Привет! Я AI-ассистент для работы с проектом.

Доступные команды:
/ask - Задать вопрос по проекту
/task - Взять задачу из Jira
/bug - Проанализировать баг по логам
/status - Статус моих задач

Выбери команду или напиши вопрос напрямую!
"""
    await message.answer(text)


@router.message(Command("ask"))
async def cmd_ask(message: Message, state: FSMContext):
    """Обработчик команды /ask"""
    await state.set_state(AskStates.waiting_for_question)
    await message.answer("📝 Напиши свой вопрос по проекту:")


@router.message(AskStates.waiting_for_question)
async def process_question(message: Message, state: FSMContext, redis_pool):
    """Обработка вопроса от пользователя"""
    question = message.text
    
    if not question:
        await message.answer("❌ Вопрос не может быть пустым")
        await state.clear()
        return
    
    await message.answer("⏳ Обрабатываю вопрос... Это может занять до 2 минут")
    
    # Добавляем задачу в очередь
    task = await redis_pool.enqueue_job(
        'process_task',
        task_id=f"ask_{message.from_user.id}_{message.message_id}",
        prompt=f"Ответь на вопрос по проекту: {question}",
        working_dir=str(settings.ML_REPO_PATH)
    )
    
    await state.clear()
    
    # Ждём результат
    try:
        result = await task.result(timeout=180)  # 3 минуты
        
        if result['success']:
            await message.answer(f"✅ Ответ:\n\n{result['output']}")
        else:
            await message.answer(f"❌ Ошибка:\n\n{result['error']}")
            
    except asyncio.TimeoutError:
        await message.answer("⏰ Превышено время ожидания. Попробуй позже.")
    except Exception as e:
        logger.error(f"Ошибка обработки вопроса: {e}")
        await message.answer(f"❌ Произошла ошибка: {str(e)}")


@router.message(Command("task"))
async def cmd_task(message: Message, state: FSMContext):
    """Обработчик команды /task"""
    await state.set_state(TaskStates.waiting_for_task_key)
    await message.answer("📋 Введи ключ задачи из Jira (например, PROJ-123):")


@router.message(TaskStates.waiting_for_task_key)
async def process_task_key(message: Message, state: FSMContext, redis_pool):
    """Обработка ключа задачи"""
    task_key = message.text.strip().upper()
    
    if not task_key or '-' not in task_key:
        await message.answer("❌ Неверный формат ключа задачи")
        await state.clear()
        return
    
    await message.answer(f"⏳ Получаю информацию о задаче {task_key}...")
    
    # Добавляем задачу в очередь
    task = await redis_pool.enqueue_job(
        'process_task',
        task_id=f"task_{message.from_user.id}_{message.message_id}",
        prompt=f"Прочитай задачу {task_key} из Jira и покажи её описание, требования и критерии приёмки",
        working_dir=str(settings.ML_REPO_PATH)
    )
    
    await state.clear()
    
    # Ждём результат
    try:
        result = await task.result(timeout=180)
        
        if result['success']:
            await message.answer(f"📋 Задача {task_key}:\n\n{result['output']}")
        else:
            await message.answer(f"❌ Ошибка:\n\n{result['error']}")
            
    except asyncio.TimeoutError:
        await message.answer("⏰ Превышено время ожидания")
    except Exception as e:
        logger.error(f"Ошибка обработки задачи: {e}")
        await message.answer(f"❌ Произошла ошибка: {str(e)}")


@router.message(Command("bug"))
async def cmd_bug(message: Message, state: FSMContext):
    """Обработчик команды /bug"""
    await state.set_state(BugStates.waiting_for_logs)
    await message.answer("🐛 Отправь лог-файл или текст с описанием бага:")


@router.message(BugStates.waiting_for_logs, F.text)
async def process_bug_text(message: Message, state: FSMContext, redis_pool):
    """Обработка текстового описания бага"""
    bug_description = message.text
    
    await message.answer("⏳ Анализирую баг...")
    
    # Добавляем задачу в очередь
    task = await redis_pool.enqueue_job(
        'process_task',
        task_id=f"bug_{message.from_user.id}_{message.message_id}",
        prompt=f"Проанализируй этот баг и найди возможные причины в коде:\n\n{bug_description}",
        working_dir=str(settings.ML_REPO_PATH)
    )
    
    await state.clear()
    
    # Ждём результат
    try:
        result = await task.result(timeout=180)
        
        if result['success']:
            await message.answer(f"🔍 Анализ бага:\n\n{result['output']}")
        else:
            await message.answer(f"❌ Ошибка:\n\n{result['error']}")
            
    except asyncio.TimeoutError:
        await message.answer("⏰ Превышено время ожидания")
    except Exception as e:
        logger.error(f"Ошибка обработки бага: {e}")
        await message.answer(f"❌ Произошла ошибка: {str(e)}")


@router.message(Command("status"))
async def cmd_status(message: Message, redis_pool):
    """Обработчик команды /status"""
    # Получаем информацию из Redis
    redis_info = await redis_pool.info()
    
    text = f"""
📊 Статус системы:

Redis:
- Подключений: {redis_info.get('connected_clients', 'N/A')}
- Используется памяти: {redis_info.get('used_memory_human', 'N/A')}

Система работает ✅
"""
    await message.answer(text)
