#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

echo "🛑 Остановка AI Assistant..."

echo "⚙️ Останавливаем Worker (systemd)..."
if systemctl list-unit-files | grep -q '^ai-assistant-worker.service'; then
    sudo systemctl stop ai-assistant-worker
else
    echo "   Юнит ai-assistant-worker не найден — пропускаю."
fi

echo "📦 Останавливаем Docker..."
docker compose down

echo "✅ Система остановлена"
