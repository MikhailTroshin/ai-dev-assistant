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
│       ├── claude_runner.py  # Обёртка для запуска Claude Code
│       └── database.py       # SQLAlchemy (SQLite) для аудита задач
├── config/
│   └── settings.py       # Конфигурация (pydantic-settings)
├── deploy/
│   ├── ai-assistant-worker.service  # Эталонный systemd-юнит для worker
│   └── install_host_deps.sh         # Установка Claude Code, Node.js, uv, MCP
├── logs/                 # Логи (не в git)
├── data/                 # БД и временные файлы (не в git)
├── .env.example          # Шаблон конфигурации (секреты в .env, не в git)
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
- Доступ к проекту, с которым будет работать ассистент

Claude Code CLI, Node.js, uv и MCP-серверы ставятся скриптом (шаг 2 ниже) — вручную ничего устанавливать не нужно.

### Установка

```bash
# 1. Клонируем репозиторий
git clone https://github.com/твой-ник/ai-dev-assistant.git
cd ai-dev-assistant

# 2. Устанавливаем хостовые зависимости (Claude Code, Node.js, uv, MCP jira/gitlab)
#    Креды можно передать через env (см. deploy/install_host_deps.sh) или ввести интерактивно:
JIRA_URL=https://your-jira.atlassian.net \
JIRA_USERNAME=your@email.com \
JIRA_API_TOKEN=... \
GITLAB_API_URL=https://gitlab.yourcompany.com/api/v4 \
GITLAB_PERSONAL_ACCESS_TOKEN=... \
./deploy/install_host_deps.sh

# 3. Создаём виртуальное окружение для worker
#    ВАЖНО: каталог должен называться именно .venv — на него рассчитаны
#    start.sh и systemd-юнит. НЕ используй имя `venv`.
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 4. Создаём .env из примера и редактируем
cp .env.example .env
$EDITOR .env   # TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_ID, пути к репо

# 5. Подготавливаем каталоги для данных и логов
mkdir -p data logs
#    Каталоги должны принадлежать пользователю, от которого работает worker.
#    Если создаёшь через sudo — исправь владельца:
#    sudo chown -R $USER:$USER data logs

# 6. Настраиваем API-модели для Claude Code (см. раздел «Конфигурация Claude Code» ниже)

# 7. Устанавливаем Worker как systemd-сервис
sudo cp deploy/ai-assistant-worker.service /etc/systemd/system/
#    При необходимости отредактируй пути (User, WorkingDirectory, PATH)
#    под своего пользователя.
sudo systemctl daemon-reload
sudo systemctl enable ai-assistant-worker

# 8. Запускаем систему
./start.sh
```

### Управление

```bash
./start.sh      # Запуск (Redis в Docker + Worker в systemd + Bot в Docker)
./stop.sh       # Остановка
./status.sh     # Статус компонентов

# Логи
docker compose logs -f bot     # Логи бота
tail -f logs/worker.log        # Логи Worker

# Управление Worker (systemd)
sudo systemctl restart ai-assistant-worker   # Перезапуск
sudo systemctl status  ai-assistant-worker   # Подробный статус
journalctl -u ai-assistant-worker -f         # Логи systemd
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
| `/project` | Выбор активного репозитория (мульти-репо) |
| `/status` | Статус системы |

Все команды выполняются **асинхронно** - бот принимает задачу и сообщает ID, а результат приходит отдельным сообщением, когда задача выполнена.

### 💬 Диалог с ассистентом (продолжение сессии)

Под каждым результатом задачи, у которой есть сессия Claude Code, появляется
кнопка **«💬 Ответить (продолжить диалог)»**. Нажатие → пишете ответ → Claude
продолжает работу **в контексте прошлой задачи** (`--resume <session_id>`):
помнит файлы, принятые решения и свои вопросы. Типовой сценарий: Claude
заканчивает ответ вопросом «делаем A, B или C?» — вы отвечаете прямо в чате.

- Диалог можно продолжать много раундов (каждый ответ — новая сессия-результат с той же историей).
- Ответ идёт через общую очередь, с таймаутом команды `reply` (по умолчанию 30 мин).
- Сессии хранятся на диске (`~/.claude/projects/...`) без явного TTL; кнопка валидна, пока жива запись в БД.

## ⚙️ Конфигурация Claude Code

Ассистент запускает Claude Code в headless-режиме (`claude -p "<промпт>"`) от имени
вашего пользователя, поэтому вся конфигурация живёт в `~/.claude/` и `~/.claude.json`.

Скрипт `deploy/install_host_deps.sh` выполняет шаги 2–4 автоматически; ниже — что
он делает и как настроить вручную.

### 1. API-модели — `~/.claude/settings.json`

Claude Code должен знать endpoint и модель (пример для прокси z.ai / GLM):

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic",
    "ANTHROPIC_AUTH_TOKEN": "sk-...",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "glm-4.7",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "glm-5.1",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "glm-5.3"
  },
  "model": "SONNET",
  "permissions": {
    "allow": [
      "Bash(*)",
      "mcp__jira",
      "mcp__gitlab"
    ],
    "defaultMode": "dontAsk"
  }
}
```

**Важно про permissions:** в headless-режиме (`dontAsk`) инструмент без записи в
`allow` молча отклоняется. Если Claude пишет «инструмент недоступен» — добавьте
`mcp__<имя-сервера>` в allowlist.

### 2. MCP-серверы — `~/.claude.json` (НЕ settings.json!)

В Claude Code >= 2.1 секция `mcpServers` из `~/.claude/settings.json`
**игнорируется** — серверы регистрируются только в `~/.claude.json`
(эквивалент `claude mcp add -s user`). Скрипт установки прописывает их туда:

```json
{
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
      "args": ["-y", "@zereight/mcp-gitlab@latest"],
      "env": {
        "GITLAB_PERSONAL_ACCESS_TOKEN": "glpat-...",
        "GITLAB_API_URL": "https://gitlab.yourcompany.com/api/v4"
      }
    }
  }
}
```

### 3. Runtime-зависимости MCP

- **gitlab** MCP запускается через `npx` → нужен **Node.js** (скрипт ставит
  standalone-дистрибутив в `~/.local/opt/node`, симлинки в `~/.local/bin`)
- **jira** MCP запускается через `uvx` → нужен **uv** (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- `~/.local/bin` должен быть в PATH юзера и в `Environment=PATH` systemd-юнита
  worker'а (в эталонном `deploy/ai-assistant-worker.service` уже учтено)

### 4. Проверка

```bash
claude mcp list
# jira:   uvx mcp-atlassian==0.21.0 - ✔ Connected
# gitlab: npx -y @zereight/mcp-gitlab@latest - ✔ Connected
```

Headless-проверка как это делает worker:

```bash
cd /path/to/target/repo
claude -p "Using the gitlab MCP tool get_merge_request fetch MR iid 1 from project group/repo. Reply with the MR title"
```

### Почему worker не в Docker

Worker сознательно запущен на хосте через systemd: ему нужен прямой доступ к
файлам целевых репозиториев, `claude` CLI c вашей конфигурацией (`~/.claude*`),
SSH-ключам и git-кредам для push. В Docker (redis, bot) попадают только
компоненты без хостовых зависимостей — поэтому перенос на новый стенд = клон
репо + `install_host_deps.sh` + `cp .env.example .env` + установка systemd-юнита.

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

### Общая первичная проверка

```bash
./status.sh                          # Состояние всех компонентов
redis-cli ping                       # Доступен ли Redis
sudo journalctl -u ai-assistant-worker -n 50   # Логи systemd для worker
tail -n 50 logs/worker.log           # Логи приложения
docker compose logs --tail=50 bot    # Логи бота
```

### Worker падает с `exit-code 203/EXEC`

Systemd не может запустить процесс. Причины:
- **Неверный путь к venv.** Юнит ожидает `.venv/bin/...`. Если каталог называется `venv` — пересоздай как `.venv` (см. раздел «Установка»), либо отредактируй `deploy/ai-assistant-worker.service`.
- **Битый shebang в `.venv/bin/arq`.** Если venv был перемещён/переименован, shebang указывает на несуществующий python. Симптом: `/home/.../.venv/bin/arq: cannot execute: required file not found`. Решение — в эталонном юните worker запускается через `python3.12 -m arq ...` (модулем), что обходит битые shebang. Не заменяй `ExecStart` на прямой вызов `arq`.

```bash
sudo systemctl status ai-assistant-worker   # посмотреть код завершения
sudo journalctl -u ai-assistant-worker -n 50
```

### Worker: `[Errno 2] No such file or directory: 'claude'`

Worker не находит Claude Code CLI. Причина: systemd не подгружает `~/.bashrc` и не видит `~/.local/bin`, куда обычно ставится `claude`. Решение — `~/.local/bin` должен быть в `Environment=PATH=...` в юните:

```bash
grep PATH /etc/systemd/system/ai-assistant-worker.service
# должно быть: Environment="PATH=/home/<user>/.local/bin:/home/<user>/ai_assistant/.venv/bin:..."
```

Если строчки нет — скопируй актуальный `deploy/ai-assistant-worker.service` и `daemon-reload`.

### Worker: `sqlite3.OperationalError: attempt to write a readonly database`

Файл `data/assistant.db` принадлежит не тому пользователю (часто `root` после ручного запуска через sudo). Worker работает от обычного пользователя и не может писать:

```bash
ls -l data/assistant.db
sudo chown -R $USER:$USER data logs
sudo systemctl restart ai-assistant-worker
```

### Worker не видит задачи (задача принята, но результата нет)

1. Проверь, что worker активен: `systemctl is-active ai-assistant-worker` → должно быть `active`.
2. Проверь очередь в Redis: `redis-cli zcard arq:queue` — если задачи копятся, worker либо упал, либо не подключён к тому же Redis.
3. Проверь, что бот и worker смотрят на одну БД Redis (одинаковые `REDIS_HOST`/`REDIS_PORT`/`REDIS_DB`). В docker-compose бот использует `REDIS_HOST=redis`, а worker на хосте — `localhost`.

### Claude в ответе пишет «в окружении нет GitLab API-токена» / MCP-инструменты недоступны

Claude Code не подключил MCP-сервер и сделал фолбэк на SSH/git. Типовые причины:

1. **MCP прописаны в `~/.claude/settings.json`** — в Claude Code >= 2.1 эта секция
   игнорируется. Серверы должны быть в `~/.claude.json` (или через `claude mcp add -s user`).
   Проверка: `claude mcp list` — должно быть `✔ Connected`.
2. **Нет Node.js / npx** — gitlab-MCP запускается через `npx`. В чистом PATH
   systemd-worker'а его может не быть: `env -i PATH="$PATH" npx --version` из-под юнита.
   Решение: `./deploy/install_host_deps.sh` (ставит Node в `~/.local/opt/node`,
   который уже есть в PATH юнита).
3. **Инструмент не в allowlist** — в headless-режиме `dontAsk` вызов `mcp__gitlab__*`
   без `mcp__gitlab` в `permissions.allow` отклоняется. Добавь `mcp__gitlab`, `mcp__jira`
   в `~/.claude/settings.json`.

### Claude Code не отвечает / таймауты

- `which claude` — доступен ли CLI.
- `claude --version` — работает ли.
- Проверь таймауты в `.env` (`CLAUDE_TIMEOUT`, `TASK_TIMEOUT`).
- При таймауте частичный вывод и логи сохраняются в БД — смотри `/task_details <task_id>`.

### Бот не запускается

- Проверь токен в `.env`.
- Проверь, что Redis доступен из контейнера: `docker compose logs bot | grep -i redis`.
- Логи: `docker compose logs bot`.

### «Задача не найдена» в `/task_details`

Если worker упал до сохранения в БД (например, из-за `readonly database`), задача попадает в очередь, но не фиксируется. После исправления причины (см. выше) отправь задачу заново.

## 📄 Лицензия

MIT

## 👤 Автор

Создано для автоматизации разработки в команде.


Чтобы развернуть систему на другом сервере:

# 1. Клонируй репозиторий
git clone https://github.com/MikhailTroshin/ai-dev-assistant.git
cd ai-dev-assistant

# 2. Установи хостовые зависимости (Claude Code, Node.js, uv, MCP jira/gitlab)
#    Передай креды Jira/GitLab через env-переменные или введи интерактивно:
JIRA_URL=... JIRA_USERNAME=... JIRA_API_TOKEN=... \
GITLAB_API_URL=... GITLAB_PERSONAL_ACCESS_TOKEN=... \
./deploy/install_host_deps.sh
#    Затем настрой API-модели в ~/.claude/settings.json (см. раздел
#    «Конфигурация Claude Code») и проверь: claude mcp list

# 3. Создай виртуальное окружение (имя каталога — строго .venv!)
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 4. Создай .env файл
cp .env.example .env
# Заполни: TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_ID, пути к репо

# 5. Подготовь каталоги и установи права
mkdir -p data logs
sudo chown -R $USER:$USER data logs

# 6. Убедись, что Claude Code установлен и доступен
claude --version
which claude  # обычно ~/.local/bin/claude

# 7. Установи и активируй systemd-юнит для worker
sudo cp deploy/ai-assistant-worker.service /etc/systemd/system/
#    Отредактируй пути внутри файла под своего пользователя!
sudo systemctl daemon-reload
sudo systemctl enable ai-assistant-worker

# 8. Запусти систему
./start.sh