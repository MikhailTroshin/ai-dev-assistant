#!/bin/bash

echo "📊 Статус AI Assistant"
echo ""

echo "🐳 Docker контейнеры:"
docker compose ps

echo ""
echo "⚙️ Worker процессы:"
ps aux | grep "arq src.worker.worker" | grep -v grep

echo ""
echo "📈 Redis:"
redis-cli ping

echo ""
echo "📝 Последние логи Worker:"
tail -n 10 logs/worker.log 2>/dev/null || echo "Worker не запущен"