#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

echo "📊 Статус AI Assistant"
echo ""

echo "⚙️ Worker:"
if systemctl cat ai-assistant-worker >/dev/null 2>&1; then
    state=$(systemctl is-active ai-assistant-worker 2>/dev/null || echo unknown)
    echo "   Юнит установлен. Состояние: ${state}"
    if [ "$state" != "active" ]; then
        echo "   ⚠️  Worker не активен! Логи:"
        tail -n 5 logs/worker.log 2>/dev/null || true
        echo "   Подсказка: sudo systemctl restart ai-assistant-worker"
    fi
    # Хвост лога для живого воркера
    if [ "$state" = "active" ]; then
        echo "   Последнее событие: $(grep -E 'ПОЛУЧЕНА ЗАДАЧА|завершена|ERROR' logs/worker.log 2>/dev/null | tail -1)"
    fi
else
    echo "   ⚠️  Юнит ai-assistant-worker не установлен в systemd."
    echo "      Установи: sudo cp deploy/ai-assistant-worker.service /etc/systemd/system/ && sudo systemctl daemon-reload"
fi

echo ""
echo "🐳 Docker контейнеры:"
docker compose ps 2>/dev/null || echo "   Docker не запущен или docker compose недоступен"

echo ""
echo "📈 Redis:"
if command -v redis-cli >/dev/null 2>&1; then
    redis-cli ping 2>/dev/null || echo "   Redis недоступен"
else
    docker compose exec -T redis redis-cli ping 2>/dev/null || echo "   redis-cli не установлен и Redis недоступен через docker"
fi

echo ""
echo "📝 Последние логи Worker:"
tail -n 10 logs/worker.log 2>/dev/null || echo "   Логи недоступны"
