import asyncio
import json
import logging
from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import redis.asyncio as redis

from src.core.database import db
from config.settings import settings

logger = logging.getLogger(__name__)

router = Router()


# ==================== FSM States ====================

class AskStates(StatesGroup):
    """Состояния для команды /ask"""
    waiting_for_question = State()


class TaskStates(StatesGroup):
    """Состояния для команды /task"""
    waiting_for_task_key = State()


class BugStates(StatesGroup):
    """Состояния для команды /bug"""
    waiting_for_logs = State()


class ReviewStates(StatesGroup):
    """Состояния для команды /code-review"""
    waiting_for_jira_key = State()


class RebaseStates(StatesGroup):
    """Состояния для команды /rebase"""
    waiting_for_branches = State()


class DetailsStates(StatesGroup):
    """Состояния для команды /task_details"""
    waiting_for_task_id = State()


# ==================== Клавиатура ====================

# Алиасы: подпись кнопки -> имя команды, которую она запускает.
# Нажатие кнопки запускает тот же флоу, что и команда.
BUTTON_ALIASES: dict[str, str] = {
    "❓ Вопрос": "ask",
    "📋 Задача Jira": "task",
    "🐛 Баг": "bug",
    "🔍 Code Review": "code-review",
    "🔧 Rebase": "rebase",
    "📜 История": "history",
    "📈 Статистика": "stats",
    "🔎 Детали задачи": "task_details",
    "📊 Статус": "status",
}


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """
    Главная клавиатура с основными командами.
    resize_keyboard=True - кнопки компактные; is_persistent - не пропадает.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❓ Вопрос"), KeyboardButton(text="📋 Задача Jira")],
            [KeyboardButton(text="🐛 Баг"), KeyboardButton(text="🔍 Code Review")],
            [KeyboardButton(text="🔧 Rebase")],
            [
                KeyboardButton(text="📜 История"),
                KeyboardButton(text="📈 Статистика"),
            ],
            [KeyboardButton(text="🔎 Детали задачи"), KeyboardButton(text="📊 Статус")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


class _RedisPoolHolder:
    """Контейнер для redis_pool, доступный из обработчиков кнопок и _submit_*."""
    pool = None


def set_redis_pool(pool) -> None:
    """Вызывается из main.py после создания пула arq."""
    _RedisPoolHolder.pool = pool


# ==================== Utility Functions ====================

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


async def send_long_message(message_or_bot, text: str, chat_id: int = None):
    """
    Отправляет длинное сообщение, разбивая на части.
    Работает как с Message, так и с Bot (для фоновых задач).
    """
    parts = split_message(text)
    
    for i, part in enumerate(parts, 1):
        if len(parts) > 1:
            content = f"📄 Часть {i}/{len(parts)}:\n\n{part}"
        else:
            content = part
        
        if chat_id:
            # Отправка через Bot (для фоновых задач)
            await message_or_bot.send_message(chat_id, content)
        else:
            # Отправка через Message (reply)
            await message_or_bot.answer(content)
        
        await asyncio.sleep(0.5)  # Небольшая пауза между сообщениями


async def save_task_mapping(task_id: str, chat_id: int, user_id: int):
    """Сохраняет связь task_id → chat_id в Redis"""
    redis_client = redis.from_url(
        f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
    )
    await redis_client.hset(
        "task_chat_mapping",
        task_id,
        json.dumps({"chat_id": chat_id, "user_id": user_id})
    )
    await redis_client.close()


def _command_args(message_text: str) -> str | None:
    """
    Если сообщение - команда с аргументами (например '/code-review AA-123'),
    возвращает аргумент-строку. Иначе None.
    """
    parts = message_text.split(maxsplit=1)
    if len(parts) < 2:
        return None
    return parts[1].strip()


# ==================== Базовые команды ====================

@router.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    text = """
👋 Привет! Я AI-ассистент для работы с проектом.

Выбери команду на клавиатуре ниже 👇 или отправь её текстом.
После выбора команды я спрошу нужные аргументы следующим сообщением.

📌 Основные команды:
/ask - Задать вопрос по проекту
/task - Получить информацию о задаче из Jira
/bug - Проанализировать баг по логам/описанию
/code-review - Code review по задаче Jira
/rebase - Rebase ветки с AI-помощью

📊 Мониторинг:
/history - Мои последние задачи
/stats - Статистика системы
/task_details - Детали конкретной задачи
/status - Статус системы

⏱ Длинные задачи выполняются асинхронно — я сообщу, когда будет готово!
"""
    await message.answer(text, reply_markup=get_main_keyboard())


@router.message(Command("cancel"))
@router.message(F.text.lower() == "отмена")
async def cmd_cancel(message: Message, state: FSMContext):
    """Сброс текущего состояния (выход из ввода аргументов)."""
    current = await state.get_state()
    if current is None:
        await message.answer("Нечего отменять 🙂", reply_markup=get_main_keyboard())
        return
    await state.clear()
    await message.answer(
        "❌ Действие отменено. Выбери команду на клавиатуре.",
        reply_markup=get_main_keyboard(),
    )


# ==================== Обработка нажатий кнопок клавиатуры ====================

@router.message(F.text.in_(BUTTON_ALIASES.keys()))
async def handle_button(message: Message, state: FSMContext):
    """
    Любая кнопка главной клавиатуры. Сбрасывает текущее состояние
    и запускает соответствующий флоу команды (с запросом аргументов).
    """
    command = BUTTON_ALIASES[message.text]

    # Сбрасываем прошлое незавершённое состояние
    await state.clear()

    if command == "ask":
        await _enter_ask(message, state)
    elif command == "task":
        await _enter_task(message, state)
    elif command == "bug":
        await _enter_bug(message, state)
    elif command == "code-review":
        await _enter_review(message, state)
    elif command == "rebase":
        await _enter_rebase(message, state)
    elif command == "task_details":
        await _enter_details(message, state)
    elif command == "history":
        await cmd_history(message)
    elif command == "stats":
        await cmd_stats(message)
    elif command == "status":
        await cmd_status(message, _RedisPoolHolder.pool)


# ==================== /ask ====================

async def _enter_ask(message: Message, state: FSMContext):
    """Начало флоу /ask (команда без аргументов / кнопка)."""
    await state.set_state(AskStates.waiting_for_question)
    await message.answer("📝 Напиши свой вопрос по проекту:")


@router.message(Command("ask"))
async def cmd_ask(message: Message, state: FSMContext):
    """
    Обработчик команды /ask.
      • /ask <вопрос>  — вопрос передан сразу
      • /ask           — спрашиваем вопрос следующим сообщением
    """
    inline = _command_args(message.text)
    if inline:
        await state.clear()
        await _submit_ask(message, inline)
        return
    await _enter_ask(message, state)


@router.message(AskStates.waiting_for_question)
async def process_question(message: Message, state: FSMContext, redis_pool):
    """Обработка вопроса от пользователя"""
    question = message.text

    if not question:
        await message.answer("❌ Вопрос не может быть пустым")
        await state.clear()
        return

    await state.clear()
    await _submit_ask(message, question, redis_pool)


async def _submit_ask(message: Message, question: str, redis_pool=None):
    """Фактическая постановка задачи ask в очередь."""
    redis_pool = redis_pool or _RedisPoolHolder.pool
    task_id = f"ask_{message.from_user.id}_{message.message_id}"

    await message.answer(
        f"⏳ Задача принята!\n"
        f"ID: `{task_id}`\n\n"
        f"Сообщу, когда будет готово (может занять до 10 минут)",
        parse_mode="Markdown"
    )

    await redis_pool.enqueue_job(
        'process_task',
        task_id=task_id,
        prompt=f"Ответь на вопрос по проекту: {question}",
        working_dir=str(settings.ML_REPO_PATH),
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        command="ask"
    )

    await save_task_mapping(task_id, message.chat.id, message.from_user.id)


# ==================== /task ====================

async def _enter_task(message: Message, state: FSMContext):
    """Начало флоу /task (команда без аргументов / кнопка)."""
    await state.set_state(TaskStates.waiting_for_task_key)
    await message.answer("📋 Введи ключ задачи из Jira (например, PROJ-123):")


@router.message(Command("task"))
async def cmd_task(message: Message, state: FSMContext):
    """Обработчик команды /task. Поддерживает inline-аргумент."""
    inline = _command_args(message.text)
    if inline:
        await state.clear()
        await _submit_task(message, inline, _RedisPoolHolder.pool)
        return
    await _enter_task(message, state)


@router.message(TaskStates.waiting_for_task_key)
async def process_task_key(message: Message, state: FSMContext, redis_pool):
    """Обработка ключа задачи"""
    task_key = (message.text or "").strip().upper()

    if not task_key or '-' not in task_key:
        await message.answer("❌ Неверный формат ключа задачи")
        await state.clear()
        return

    await state.clear()
    await _submit_task(message, task_key, redis_pool)


async def _submit_task(message: Message, task_key: str, redis_pool=None):
    """Фактическая постановка задачи task в очередь."""
    redis_pool = redis_pool or _RedisPoolHolder.pool
    task_key = task_key.strip().upper()
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
        prompt=f"Прочитай задачу {task_key} из Jira и покажи её описание, требования и критерии приёмки. Если есть вложения - проанализируй их.",
        working_dir=str(settings.ML_REPO_PATH),
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        command="task"
    )

    await save_task_mapping(task_id, message.chat.id, message.from_user.id)


# ==================== /bug ====================

async def _enter_bug(message: Message, state: FSMContext):
    """Начало флоу /bug (команда без аргументов / кнопка)."""
    await state.set_state(BugStates.waiting_for_logs)
    await message.answer("🐛 Отправь текст с описанием бага (или логи):")


@router.message(Command("bug"))
async def cmd_bug(message: Message, state: FSMContext):
    """Обработчик команды /bug. Поддерживает inline-аргумент."""
    inline = _command_args(message.text)
    if inline:
        await state.clear()
        await _submit_bug(message, inline, _RedisPoolHolder.pool)
        return
    await _enter_bug(message, state)


@router.message(BugStates.waiting_for_logs, F.text)
async def process_bug_text(message: Message, state: FSMContext, redis_pool):
    """Обработка текстового описания бага"""
    bug_description = message.text
    await state.clear()
    await _submit_bug(message, bug_description, redis_pool)


async def _submit_bug(message: Message, bug_description: str, redis_pool=None):
    """Фактическая постановка задачи bug в очередь."""
    redis_pool = redis_pool or _RedisPoolHolder.pool
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
        user_id=message.from_user.id,
        command="bug"
    )

    await save_task_mapping(task_id, message.chat.id, message.from_user.id)


# ==================== /code-review ====================

async def _enter_review(message: Message, state: FSMContext):
    """Начало флоу /code-review (команда без аргументов / кнопка)."""
    await state.set_state(ReviewStates.waiting_for_jira_key)
    await message.answer("🔍 Введи ключ задачи из Jira для code review (например, AA-123):")


@router.message(Command("code-review"))
async def cmd_code_review(message: Message, state: FSMContext):
    """Обработчик команды /code-review. Поддерживает inline-аргумент."""
    inline = _command_args(message.text)
    if inline:
        await state.clear()
        await _submit_review(message, inline, _RedisPoolHolder.pool)
        return
    await _enter_review(message, state)


@router.message(ReviewStates.waiting_for_jira_key)
async def process_review_key(message: Message, state: FSMContext, redis_pool):
    """Обработка ключа задачи для code review"""
    jira_key = (message.text or "").strip().upper()

    if not jira_key or '-' not in jira_key:
        await message.answer("❌ Неверный формат ключа задачи")
        await state.clear()
        return

    await state.clear()
    await _submit_review(message, jira_key, redis_pool)


async def _submit_review(message: Message, jira_key: str, redis_pool=None):
    """Фактическая постановка задачи code-review в очередь."""
    redis_pool = redis_pool or _RedisPoolHolder.pool
    jira_key = jira_key.strip().upper()
    task_id = f"review_{message.from_user.id}_{message.message_id}"

    await message.answer(
        f"⏳ Задача принята!\n"
        f"ID: `{task_id}`\n\n"
        f"Ищу MR по задаче {jira_key} и провожу code review...",
        parse_mode="Markdown"
    )

    prompt = f"""
    Выполни code review для задачи {jira_key}.
    1. Используй skill `jira-lookup`, чтобы найти задачу и получить ссылку на GitLab MR.
    2. Используй skill `gitlab-mr-review` (или MCP gitlab), чтобы получить diff и комментарии к MR.
    3. Проанализируй изменения. Найди потенциальные баги, проблемы с архитектурой или логикой.
    4. Верни краткий структурированный отчет на русском языке.
    """

    await redis_pool.enqueue_job(
        'process_task',
        task_id=task_id,
        prompt=prompt,
        working_dir=str(settings.ML_REPO_PATH),
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        command="code-review"
    )

    await save_task_mapping(task_id, message.chat.id, message.from_user.id)


# ==================== /rebase ====================

async def _enter_rebase(message: Message, state: FSMContext):
    """Начало флоу /rebase (команда без аргументов / кнопка)."""
    await state.set_state(RebaseStates.waiting_for_branches)
    await message.answer(
        "🔧 Введи две ветки в формате:\n"
        "<code>&lt;целевая_ветка&gt; &lt;исходная_ветка&gt;</code>\n"
        "Например: <code>master feature-branch</code>",
        parse_mode="HTML",
    )


@router.message(Command("rebase"))
async def cmd_rebase(message: Message, state: FSMContext):
    """Обработчик команды /rebase. Поддерживает inline-аргументы."""
    inline = _command_args(message.text)
    if inline and len(inline.split()) >= 2:
        await state.clear()
        await _submit_rebase(message, inline, _RedisPoolHolder.pool)
        return
    await _enter_rebase(message, state)


@router.message(RebaseStates.waiting_for_branches)
async def process_rebase_branches(message: Message, state: FSMContext, redis_pool):
    """Обработка веток для rebase"""
    args = (message.text or "").split()
    if len(args) < 2:
        await message.answer(
            "❌ Нужно две ветки: <code>&lt;целевая&gt; &lt;исходная&gt;</code>",
            parse_mode="HTML",
        )
        await state.clear()
        return

    await state.clear()
    await _submit_rebase(message, " ".join(args[:2]), redis_pool)


async def _submit_rebase(message: Message, branches: str, redis_pool=None):
    """Фактическая постановка задачи rebase в очередь."""
    redis_pool = redis_pool or _RedisPoolHolder.pool
    parts = branches.split()
    branch_a = parts[0].strip()  # целевая (куда вливаем)
    branch_b = parts[1].strip()  # исходная (которую ребейзим)
    task_id = f"rebase_{message.from_user.id}_{message.message_id}"

    await message.answer(
        f"⏳ Задача принята!\n"
        f"ID: `{task_id}`\n\n"
        f"Выполняю rebase {branch_b} onto {branch_a}.\n"
        f"Если будут конфликты, ИИ попробует их разрешить...",
        parse_mode="Markdown"
    )

    prompt = f"""
    Выполни безопасный git rebase в директории проекта.
    Целевая ветка: {branch_a}
    Исходная ветка: {branch_b}

    Строго следуй алгоритму:
    1. `git fetch --all`
    2. `git checkout {branch_b}`
    3. `git checkout -b {branch_b}_backup_{task_id}` (создай бекап ветки!)
    4. `git checkout {branch_b}`
    5. `git rebase {branch_a}`
    6. ЕСЛИ возникли конфликты:
       - Определи конфликтующие файлы через `git status`.
       - Прочитай содержимое конфликтующих файлов.
       - Проанализируй конфликт и предложи корректное решение.
       - Внеси исправления в файлы.
       - Выполни `git add <файлы>` и `git rebase --continue`.
       - Повторяй, пока rebase не завершится.
    7. Если rebase успешен, выполни `git push --force-with-lease origin {branch_b}`.
    8. Сообщай о каждом шаге. Если требуется вмешательство человека (невозможно разрешить автоматически), остановись и четко опиши проблему.
    """

    await redis_pool.enqueue_job(
        'process_task',
        task_id=task_id,
        prompt=prompt,
        working_dir=str(settings.ML_REPO_PATH),
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        command="rebase"
    )

    await save_task_mapping(task_id, message.chat.id, message.from_user.id)


# ==================== Мониторинг и статистика ====================

@router.message(Command("history"))
async def cmd_history(message: Message):
    """Показать последние задачи пользователя"""
    tasks = await db.get_user_tasks(message.from_user.id, limit=10)
    
    if not tasks:
        await message.answer("📭 У тебя пока нет выполненных задач")
        return
    
    text = "📋 Твои последние задачи:\n\n"
    for task in tasks:
        status = "✅" if task.success else "❌"
        duration = f"{task.duration_seconds:.1f}с" if task.duration_seconds else "N/A"
        text += f"{status} `{task.task_id[:25]}...`\n"
        text += f"   📌 Команда: {task.command}\n"
        text += f"   ⏱ Время: {duration}\n"
        text += f"   📅 Дата: {task.created_at.strftime('%d.%m %H:%M')}\n\n"
    
    text += "💡 Используй `/task_details <task_id>` для просмотра деталей"
    
    await message.answer(text, parse_mode="Markdown")


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Показать статистику системы"""
    stats = await db.get_stats()
    
    text = f"""
📊 Статистика системы:

📈 Всего задач: {stats['total']}
✅ Успешных: {stats['success']}
❌ Неудачных: {stats['failed']}
⏱ Среднее время: {stats['avg_duration']}с

📌 По командам:
"""
    for cmd, count in stats['by_command'].items():
        text += f"  • {cmd}: {count}\n"
    
    await message.answer(text)


# ==================== /task_details ====================

async def _enter_details(message: Message, state: FSMContext):
    """Начало флоу /task_details (команда без аргументов / кнопка)."""
    await state.set_state(DetailsStates.waiting_for_task_id)
    await message.answer("🔎 Введи task_id задачи (например, `ask_66751422_5`):", parse_mode="Markdown")


@router.message(Command("task_details"))
async def cmd_task_details(message: Message, state: FSMContext):
    """Показать детали конкретной задачи. Поддерживает inline-аргумент."""
    inline = _command_args(message.text)
    if inline:
        await state.clear()
        await _show_task_details(message, inline)
        return
    await _enter_details(message, state)


@router.message(DetailsStates.waiting_for_task_id)
async def process_details_id(message: Message, state: FSMContext):
    """Обработка task_id"""
    task_id = (message.text or "").strip()
    await state.clear()
    await _show_task_details(message, task_id)


async def _show_task_details(message: Message, task_id: str):
    """Фактический показ деталей задачи."""
    task_id = task_id.strip()
    task = await db.get_task(task_id)

    if not task:
        await message.answer(f"❌ Задача `{task_id}` не найдена", parse_mode="Markdown")
        return

    # Проверяем, что задача принадлежит пользователю (или это админ)
    if task.user_id != message.from_user.id and message.from_user.id != settings.TELEGRAM_ADMIN_ID:
        await message.answer("⛔ У тебя нет доступа к этой задаче")
        return

    text = f"""
📝 Задача: `{task.task_id}`

📌 Команда: {task.command}
{'✅ Успешно' if task.success else '❌ Ошибка'}
⏱ Время: {task.duration_seconds:.2f}с
📅 Создана: {task.created_at.strftime('%d.%m.%Y %H:%M')}
"""

    if task.completed_at:
        text += f"🏁 Завершена: {task.completed_at.strftime('%d.%m.%Y %H:%M')}\n"

    text += f"\n📄 Промпт:\n```\n{task.prompt[:500]}{'...' if len(task.prompt) > 500 else ''}\n```\n"

    if task.result:
        text += f"📄 Результат:\n```\n{task.result[:1000]}{'...' if len(task.result) > 1000 else ''}\n```\n"

    if task.error:
        text += f"⚠️ Ошибка:\n```\n{task.error}\n```\n"

    await message.answer(text, parse_mode="Markdown")


@router.message(Command("status"))
async def cmd_status(message: Message, redis_pool):
    """Обработчик команды /status"""
    # Получаем информацию из Redis
    redis_info = await redis_pool.info()
    
    # Проверяем количество ожидающих результатов
    redis_client = redis.from_url(
        f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
    )
    pending_count = await redis_client.scard("pending_results")
    await redis_client.close()
    
    text = f"""
📊 Статус системы:

🔴 Redis:
- Подключений: {redis_info.get('connected_clients', 'N/A')}
- Используется памяти: {redis_info.get('used_memory_human', 'N/A')}

📋 Задачи:
- Ожидают отправки: {pending_count}

✅ Система работает
"""
    await message.answer(text)