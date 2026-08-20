# CLAUDE.md - Инструкции для Claude Code

Этот файл содержит инструкции для Claude Code при работе над проектом AI Dev Assistant.

## 🎯 О проекте

**AI Dev Assistant** - это система автоматизации разработки на базе Claude Code. Система состоит из:
- Telegram-бота для приёма команд
- Redis-очереди для задач
- Worker'а, который запускает Claude Code для выполнения задач

**Важно:** Этот репозиторий (`ai_assistant`) - это инфраструктура ассистента. Основная работа происходит в целевом проекте (например, `ragllm`), с которым ассистент взаимодействует через Claude Code.

## 🏗️ Архитектура системы

```
Telegram Bot (Docker) → Redis (Docker) → Worker (Host) → Claude Code (Host) → Файлы проекта
```

### Ключевые компоненты

1. **`src/bot/`** - Telegram-бот на aiogram 3.x
   - `main.py` - точка входа, запуск polling, фоновая задача проверки результатов
   - `handlers.py` - обработчики команд (`/ask`, `/task`, `/bug`, `/code-review`, `/rebase`, `/status`)

2. **`src/worker/`** - Worker для arq очереди
   - `worker.py` - принимает задачи из Redis, запускает Claude Code, сохраняет результаты

3. **`src/core/claude_runner.py`** - обёртка для запуска Claude Code через subprocess
   - Использует `asyncio.create_subprocess_exec`
   - Поддерживает таймауты
   - Возвращает структурированный результат

4. **`config/settings.py`** - конфигурация через pydantic-settings
   - Читает из `.env`
   - Валидирует значения

## 📝 Стиль кода

### Python
- **Версия:** Python 3.12
- **Стиль:** PEP 8, но с современными практиками
- **Типизация:** Используй type hints везде
- **Async:** Весь код асинхронный (asyncio)
- **Импорты:** Группируй (стандартные → сторонние → локальные)
- **Логирование:** Используй `logging.getLogger(__name__)`
- **Конфигурация:** Только через `config.settings`

### Пример правильного кода

```python
import asyncio
import logging
from pathlib import Path
from typing import Optional

from config.settings import settings

logger = logging.getLogger(__name__)


async def process_something(
    task_id: str,
    data: str,
    timeout: Optional[int] = None
) -> dict:
    """
    Краткое описание функции.
    
    Args:
        task_id: ID задачи
        data: Входные данные
        timeout: Таймаут в секундах
        
    Returns:
        dict с результатами
    """
    timeout = timeout or settings.DEFAULT_TIMEOUT
    logger.info(f"Обработка задачи {task_id}")
    
    try:
        result = await some_async_operation(data)
        return {"success": True, "result": result}
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        return {"success": False, "error": str(e)}
```

## 🔧 Работа с проектом

### Запуск и тестирование

```bash
./start.sh              # Запуск всей системы (Redis + Bot в Docker, Worker в systemd)
./stop.sh               # Остановка
./status.sh             # Статус

docker compose logs -f bot     # Логи бота
tail -f logs/worker.log        # Логи Worker
sudo journalctl -u ai-assistant-worker -f   # Логи systemd для Worker

# Управление Worker
sudo systemctl restart ai-assistant-worker
sudo systemctl status  ai-assistant-worker

# Тест конкретного компонента
python tests/test_claude_simple.py
python tests/test_claude_async.py
python tests/test_worker.py
```

### systemd-юнит Worker'а

Worker работает как systemd-сервис `ai-assistant-worker`. Эталонный файл —
`deploy/ai-assistant-worker.service`. Особенности:

1. Worker запускается от обычного пользователя (владельца каталога проекта),
   НЕ от root. Иначе будет `readonly database` при записи в SQLite.
2. В `Environment=PATH=...` обязательно включён `~/.local/bin`, где лежит
   `claude` CLI. Без него будет `[Errno 2] No such file or directory: 'claude'`.
3. Worker запускается через `python3.12 -m arq ...`, а не через скрипт
   `.venv/bin/arq` (shebang которого ломается при перемещении venv).
4. Виртуальное окружение должно называться **`.venv`** (не `venv`).

После изменения `deploy/ai-assistant-worker.service`:
```bash
sudo cp deploy/ai-assistant-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart ai-assistant-worker
```

### Структура задач

Задачи выполняются **асинхронно**:
1. Бот принимает команду от пользователя
2. Создаёт задачу в Redis с `task_id`
3. Worker берёт задачу, запускает Claude Code
4. Claude Code выполняет задачу (может занять 1-10 минут)
5. Результат сохраняется в Redis
6. Бот (фоновая задача) видит результат и отправляет пользователю

### Работа с Claude Code

Когда ты (Claude Code) вызываешься worker'ом:
- Ты работаешь в контексте целевого проекта (например, `ragllm`)
- У тебя есть доступ к файлам проекта
- Ты можешь использовать MCP-серверы (Jira, GitLab)
- Ты должен вернуть структурированный результат

## 🤖 Команды бота и их обработка

### `/ask <вопрос>`
- **Что делает:** Задаёт вопрос по проекту
- **Как обрабатывать:** Читать файлы проекта, историю коммитов, документацию
- **Формат ответа:** Markdown, структурированный

### `/task <JIRA_KEY>`
- **Что делает:** Получает информацию о задаче из Jira
- **Как обрабатывать:** 
  1. Использовать skill `jira-lookup` или скрипт `~/.claude/scripts/jira_query.py`
  2. Если есть вложения - скачать и проанализировать
  3. Для текстовых файлов - читать содержимое
  4. Для архивов - распаковать и анализировать файлы
  5. Для картинок - использовать vision
- **Формат ответа:** Описание задачи + анализ вложений

### `/bug <описание>`
- **Что делать:** Анализировать баг по описанию и/или логам
- **Как обрабатывать:**
  1. Искать ошибки в логах
  2. Находить соответствующий код в проекте
  3. Анализировать возможные причины
  4. Предлагать исправления
- **Формат ответа:** Анализ + предложения по фиксу

### `/code-review <JIRA_KEY>`
- **Что делает:** Code review MR по задаче из Jira
- **Как обрабатывать:**
  1. Получить задачу из Jira через `jira_query.py`
  2. Найти ссылку на MR в описании или комментариях
  3. Извлечь MR IID из ссылки
  4. Использовать GitLab MCP для получения diff
  5. Проанализировать изменения
  6. Найти баги, проблемы с архитектурой, edge cases
  7. **Игнорировать** мелкие стилистические замечания
- **Формат ответа:** Структурированный Markdown отчёт

### `/rebase <source_branch> <target_branch>`
- **Что делает:** Rebase ветки с AI-разрешением конфликтов
- **Как обрабатывать (СТРОГО по алгоритму):**
  1. `git fetch --all`
  2. `git checkout <source_branch>`
  3. `git checkout -b <source_branch>_backup_<task_id>` (создать бекап!)
  4. `git checkout <source_branch>`
  5. `git rebase <target_branch>`
  6. **ЕСЛИ конфликты:**
     - `git status` для определения конфликтующих файлов
     - Прочитать конфликтующие файлы
     - Проанализировать конфликт
     - Внести исправления через Edit
     - `git add <файлы>`
     - `git rebase --continue`
     - Повторять до завершения
  7. Если успешно: `git push --force-with-lease origin <source_branch>`
  8. Сообщать о каждом шаге
  9. Если невозможно разрешить автоматически - остановиться и описать проблему
- **Формат ответа:** Лог выполнения + результат

## 🔗 Интеграция с Jira

### Скрипт `~/.claude/scripts/jira_query.py`

Используй этот скрипт для получения задач:

```bash
~/.claude/scripts/jira_query.py AA-123
```

**Что возвращает:**

```json
{
  "key": "AA-123",
  "summary": "Название задачи",
  "status": "In Progress",
  "priority": "High",
  "description": "Описание",
  "attachments": [
    {
      "filename": "log.txt",
      "type": "file",
      "local_path": "/tmp/jira_attachments/AA-123/log.txt"
    },
    {
      "filename": "data.zip",
      "type": "archive",
      "local_path": "/tmp/jira_attachments/AA-123/data.zip",
      "extracted_path": "/tmp/jira_attachments/AA-123/data.zip_extracted"
    }
  ]
}
```

**Как работать с вложениями:**
- `type: "file"` - прочитать файл по `local_path`
- `type: "archive"` - анализировать файлы в `extracted_path`
- `type: "image"` - использовать vision для анализа картинки

## 🔗 Интеграция с GitLab

### MCP-сервер GitLab

Используй MCP-сервер `gitlab` для операций с GitLab:

**Получить MR:**

```
get_merge_request(
  project_id="naumen/ragllm",
  merge_request_iid=456,
  include_diverged_commits_count=true,
  include_rebase_in_progress=true
)
```

**Получить изменения MR:**

```
get_merge_request_changes(
  project_id="naumen/ragllm",
  merge_request_iid=456
)
```

## 📚 Работа с целевым проектом (ragllm)

Когда ты работаешь с проектом `ragllm`:

### Структура проекта
- `rag_llm/` - основной пакет
  - `parsers/` - парсеры документов
  - `retriever/` - поиск релевантных чанков
  - `reranker/` - переранжирование
  - `generator/` - генерация ответов (langgraph workflows)
  - `db/` - работа с PostgreSQL
  - `grpc/` - proto-файлы
  - `infrastructure/` - логирование, трейсинг
  - `configs/` - конфигурации
- `scripts/` - утилиты
- `tests/` - тесты

### Архитектура

```
Parser → Retriever (+Reranker) → Generator
```

### Важные моменты
- Проект использует gRPC для межсервисного взаимодействия
- Generator использует LangGraph для workflows
- Есть BM25, BERT, DSI индексы в retriever
- Конфигурации шаблонизированы

## ⚠️ Важные правила

### Безопасность
- **НИКОГДА** не коммить `.env` файлы
- **НИКОГДА** не логируй токены и пароли
- **ВСЕГДА** проверяй, что работаешь в правильной директории

### Git операции
- **ВСЕГДА** создавай бекап-ветку перед rebase
- **ИСПОЛЬЗУЙ** `--force-with-lease` вместо `--force`
- **ПРОВЕРЯЙ** `git status` перед каждым коммитом

### Обработка ошибок
- **ВСЕГДА** возвращай структурированный результат: `{"success": bool, "output": str, "error": str | None}`
- **ЛОГИРУЙ** все важные шаги
- **НЕ ПАНИКУЙ** при ошибках - опиши проблему чётко

### Производительность
- **ИСПОЛЬЗУЙ** асинхронные операции где возможно
- **КЭШИРУЙ** результаты если нужно
- **ОГРАНИЧИВАЙ** глубину чтения файлов (не читай всё сразу)

## 🧪 Тестирование изменений

Перед коммитом изменений в `ai_assistant`:

1. **Проверь синтаксис:**
   ```bash
   python -m py_compile src/bot/main.py
   python -m py_compile src/worker/worker.py
   ```

2. **Запусти тесты:**
   ```bash
   python tests/test_claude_simple.py
   python tests/test_claude_async.py
   python tests/test_worker.py
   ```

3. **Проверь Docker:**
   ```bash
   docker compose config
   ```

4. **Проверь логи:**
   ```bash
   ./start.sh
   ./status.sh
   docker compose logs -f
   ```

## 📖 Дополнительные ресурсы

- **README.md** - описание проекта для людей
- **`~/.claude/skills/`** - навыки для Claude Code
- **`~/.claude/scripts/`** - вспомогательные скрипты
- **Логи** - `logs/` и `docker compose logs`

## 🎯 Чек-лист перед завершением задачи

- [ ] Код соответствует стилю (PEP 8, type hints, async)
- [ ] Добавлено логирование важных шагов
- [ ] Обработаны ошибки (try/except)
- [ ] Протестировано локально
- [ ] Обновлена документация (если нужно)
- [ ] Не закоммичены секреты (.env, токены)

---

**Помни:** Ты работаешь в инфраструктурном проекте. Твоя задача - сделать систему надёжной, переносимой и удобной для использования. Если что-то непонятно - спрашивай!