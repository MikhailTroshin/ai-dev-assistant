#!/bin/bash

echo "🚀 Запуск AI Assistant..."

# Запускаем Docker контейнеры (Redis + Bot)
echo "📦 Запускаем Redis и Bot в Docker..."
docker compose up -d --build

# Запускаем Worker на хосте
echo "⚙️ Запускаем Worker на хосте..."
source venv/bin/activate
nohup arq src.worker.worker.WorkerSettings > logs/worker.log 2>&1 &

echo "✅ Система запущена!"
echo "   Redis + Bot: в Docker"
echo "   Worker: на хосте (PID: $!)"
echo ""
echo "Логи:"
echo "  Docker: docker compose logs -f"
echo "  Worker: tail -f logs/worker.log"