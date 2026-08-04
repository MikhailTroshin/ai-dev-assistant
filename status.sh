#!/bin/bash

echo "📊 Статус AI Assistant"
echo ""

echo "⚙️ Worker:"
sudo systemctl status ai-assistant-worker --no-pager -l | head -n 15

echo ""
echo "🐳 Docker контейнеры:"
docker compose ps

echo ""
echo "📈 Redis:"
redis-cli ping

echo ""
echo "📝 Последние логи Worker:"
tail -n 10 logs/worker.log 2>/dev/null || echo "Логи недоступны"