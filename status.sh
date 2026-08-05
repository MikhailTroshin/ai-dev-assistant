#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

echo "📊 Статус AI Assistant"
echo ""

echo "⚙️ Worker:"
if systemctl list-unit-files 2>/dev/null | grep -q '^ai-assistant-worker.service'; then
    # systemd нужен sudo для статуса; если нет прав — показываем подсказку
    if sudo -n true 2>/dev/null; then
        systemctl status ai-assistant-worker --no-pager -l | head -n 15
    else
        echo "   (для подробного статуса выполните: sudo systemctl status ai-assistant-worker)"
        systemctl is-active ai-assistant-worker 2>/dev/null || true
    fi
else
    echo "   ⚠️  Юнит ai-assistant-worker не установлен в systemd."
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
