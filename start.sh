#!/bin/bash
set -euo pipefail

# Переходим в каталог скрипта (работает из любого места)
cd "$(dirname "$0")"

echo "🚀 Запуск AI Assistant..."

# Проверки предусловий
if [ ! -d ".venv" ]; then
    echo "❌ Не найдено виртуальное окружение .venv"
    echo "   Создай его: python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

if ! command -v claude >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/claude" ]; then
    echo "⚠️  Предупреждение: команда 'claude' не найдена в PATH и в ~/.local/bin."
    echo "   Worker не сможет запускать Claude Code. Продолжаю..."
fi

# Запускаем Redis
echo "📦 Запускаем Redis в Docker..."
docker compose up -d redis

# Запускаем Worker через systemd
echo "⚙️ Запускаем Worker (systemd)..."
if systemctl is-enabled --quiet ai-assistant-worker 2>/dev/null; then
    sudo systemctl start ai-assistant-worker
else
    echo "⚠️  Юнит ai-assistant-worker не установлен."
    echo "   Установи: sudo cp deploy/ai-assistant-worker.service /etc/systemd/system/ && sudo systemctl daemon-reload"
    exit 1
fi

# Запускаем бота в Docker
echo "🤖 Запускаем Bot в Docker..."
docker compose up -d bot

echo "✅ Система запущена!"
echo ""
echo "Статус:    ./status.sh"
echo "Логи:"
echo "  Worker:  tail -f logs/worker.log"
echo "  Bot:     docker compose logs -f bot"
echo "  Redis:   docker compose logs -f redis"
