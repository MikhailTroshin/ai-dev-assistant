# AI Dev Assistant

Автоматизированный AI-ассистент для разработки, построенный на базе Claude Code. Система принимает задачи через Telegram, выполняет их через Claude Code (с использованием MCP-серверов) и возвращает результаты пользователю.

## 🎯 Возможности

- **Автоматическое выполнение задач** из Jira с созданием кода, веток и коммитов
- **Code Review** по номеру задачи из Jira (анализ MR в GitLab)
- **Автоматический Rebase** с AI-разрешением конфликтов
- **Анализ багов** по логам и описаниям
- **Ответы на вопросы** по проекту с использованием контекста
- **Работа с вложениями** Jira (логи, архивы, текстовые файлы)

## 🏗️ Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Containers                        │
│  ┌──────────────┐  ┌──────────────┐                         │
│  │  Redis       │  │  Telegram    │                         │
│  │  (очередь)   │←→│  Bot         │                         │
│  └──────────────┘  └──────────────┘                         │
└─────────────────────────────────────────────────────────────┘
                         │
                         │ (через Redis)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    Host (Ubuntu)                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  Worker      │→ │ Claude Code  │→ │  Файлы       │       │
│  │  (Python)    │  │ (CLI)        │  │  проекта     │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│         │                                                   │
│         └→ MCP-серверы (Jira, GitLab, qmd)                  │
└─────────────────────────────────────────────────────────────┘
```

### Компоненты

**В Docker:**
- **Redis** - очередь задач (arq)
- **Telegram Bot** - приём команд от пользователя, отправка результатов

**На хосте:**
- **Worker** - Python-процесс, берёт задачи из Redis, запускает Claude Code
- **Claude Code** - CLI-инструмент, выполняет задачи, работает с файлами проекта
- **MCP-серверы** - интеграция с Jira, GitLab и другими инструментами

### Почему такое разделение?

- **Docker** для Redis и Bot - переносимость, изоляция, простой деплой
- **Worker на хосте** - нужен прямой доступ к `claude` CLI и файловой системе
- **Claude Code на хосте** - работает с реальным репозиторием, использует MCP-серверы

## 📦 Структура проекта

```
ai_assistant/
├── src/
│   ├── bot/              # Telegram-бот
│   │   ├── main.py       # Точка входа бота
│   │   └── handlers.py   # Обработчики команд
│   ├── worker/           # Worker для очереди
│   │   └── worker.py     # Обработчик задач
│   └── core/             # Общая логика
│       └── claude_runner.py  # Обёртка для запуска Claude Code
├── config/
│   └── settings.py       # Конфигурация (pydantic-settings)
├── logs/                 # Логи (не в git)
├── data/                 # БД и временные файлы (не в git)
├── .env                  # Секреты (не в git)
├── docker-compose.yml    # Docker конфигурация
├── Dockerfile.bot        # Dockerfile для бота
├── requirements.txt      # Зависимости для worker (на хосте)
├── requirements-bot.txt  # Зависимости для бота (в Docker)
├── start.sh              # Запуск системы
├── stop.sh               # Остановка системы
├── status.sh             # Проверка статуса
├── CLAUDE.md             # Инструкции для Claude Code
└── README.md             # Этот файл
```

## 🚀 Быстрый старт

### Требования

- Ubuntu 22.04+ (или другой Linux)
- Python 3.12+
- Docker и Docker Compose
- Claude Code CLI (установлен и настроен)
- Доступ к проекту, с которым будет работать ассистент

### Установка

```bash
# 1. Клонируем репозиторий
git clone https://github.com/твой-ник/ai-dev-assistant.git
cd ai-dev-assistant

# 2. Создаём виртуальное окружение для worker
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Создаём .env файл (отредактируй значения под себя!)
cat > .env << 'EOF'
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
PROJECT_PATH=/home/ws/mtroshin/ai_assistant
ML_REPO_PATH=/home/ws/mtroshin/ragllm
CLAUDE_CODE_PATH=claude
CLAUDE_TIMEOUT=600
DATABASE_URL=sqlite+aiosqlite:///data/assistant.db
LOG_LEVEL=INFO
LOG_FILE=logs/assistant.log
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_ADMIN_ID=your_telegram_user_id
TASK_TIMEOUT=900
POLL_INTERVAL=5
EOF

# 4. Запускаем систему
./start.sh
```

### Управление

```bash
./start.sh      # Запуск
./stop.sh       # Остановка
./status.sh     # Статус

docker compose logs -f      # Логи Docker (Redis + Bot)
tail -f logs/worker.log     # Логи Worker
```

## 🤖 Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие и список команд |
| `/ask <вопрос>` | Задать вопрос по проекту |
| `/task <JIRA_KEY>` | Получить информацию о задаче из Jira |
| `/bug <описание>` | Проанализировать баг |
| `/code-review <JIRA_KEY>` | Code review MR по задаче |
| `/rebase <target> <source>` | Rebase ветки с AI-разрешением конфликтов |
| `/status` | Статус системы |

Все команды выполняются **асинхронно** - бот принимает задачу и сообщает ID, а результат приходит отдельным сообщением, когда задача выполнена.

## ⚙️ Конфигурация Claude Code

Для работы ассистента в целевом проекте (например, `ragllm`) должен быть настроен `.claude/settings.json`:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://your-api.com",
    "ANTHROPIC_AUTH_TOKEN": "sk-..."
  },
  "permissions": {
    "allow": [
      "Bash(*)",
      "Edit(*)",
      "Read(*)",
      "WebFetch(*)",
      "TodoWrite(*)"
    ],
    "defaultMode": "dontAsk"
  },
  "mcpServers": {
    "jira": {
      "command": "uvx",
      "args": ["mcp-atlassian==0.21.0"],
      "env": {
        "JIRA_URL": "https://your-jira.atlassian.net",
        "JIRA_USERNAME": "your@email.com",
        "JIRA_API_TOKEN": "ATAT..."
      }
    },
    "gitlab": {
      "command": "npx",
      "args": [
        "-y",
        "@zereight/mcp-gitlab",
        "--token=YOUR_TOKEN",
        "--api-url=https://gitlab.yourcompany.com/api/v4"
      ]
    }
  }
}
```

## 📋 Этапы развития

### ✅ Этап 1: Базовая инфраструктура
- Структура проекта
- Redis очередь
- Worker для задач
- CLI-обёртка для Claude Code

### ✅ Этап 2: Telegram-бот
- Команды `/ask`, `/task`, `/bug`, `/status`
- Асинхронное выполнение задач
- Разбиение длинных сообщений
- Фоновая проверка результатов

### 🔄 Этап 3: MCP-серверы и новые команды (текущий)
- Jira с вложениями
- GitLab MCP
- `/code-review` команда
- `/rebase` команда

### 📝 Этап 4: База знаний
- qmd для документации
- Индексация файлов
- RAG для контекста

### 📊 Этап 5: Мониторинг
- База данных для аудита
- Метрики использования токенов
- Дашборд

### 🐳 Этап 6: Полная контейнеризация
- Опциональная контейнеризация worker
- Скрипты автоматического деплоя
- Документация для переноса

## 🔒 Безопасность

- **Секреты** хранятся в `.env` (не в git)
- **Claude Code** работает в режиме `dontAsk` только в папке проекта
- **Redis** доступен только на localhost
- **Worker** изолирован в виртуальном окружении

## 🐛 Troubleshooting

### Worker не видит задачи
- Проверь, что Redis запущен: `redis-cli ping`
- Проверь имя очереди: `redis-cli KEYS '*queue*'`

### Claude Code не отвечает
- Проверь, что `claude` доступен: `which claude`
- Проверь таймауты в `.env`
- Посмотри логи: `tail -f logs/worker.log`

### Бот не запускается
- Проверь токен в `.env`
- Проверь, что Redis доступен из контейнера
- Логи: `docker compose logs bot`

## 📄 Лицензия

MIT

## 👤 Автор

Создано для автоматизации разработки в команде.


Чтобы развернуть систему на другом сервере:

# 1. Клонируй репозиторий
git clone https://github.com/MikhailTroshin/ai-dev-assistant.git
cd ai-dev-assistant

# 2. Создай виртуальное окружение и установи зависимости
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Создай .env файл
cp .env.example .env  # или создай вручную
# Заполни: TELEGRAM_BOT_TOKEN, REDIS_HOST, пути к проекту

# 4. Убедись, что Claude Code установлен и настроен
claude --version

# 5. Запусти систему
./start.sh