#!/bin/bash

echo "🚀 Запуск AI Assistant..."

# Запускаем Docker контейнеры (Redis)
echo "📦 Запускаем Redis в Docker..."
docker compose up -d redis

# Запускаем Worker через systemd
echo "⚙️ Запускаем Worker через systemd..."
sudo systemctl start ai-assistant-worker

# Опционально: запускаем бот в Docker
echo "🤖 Запускаем Bot в Docker..."
docker compose up -d bot

echo "✅ Система запущена!"
echo ""
echo "Статус:"
echo "  Worker: sudo systemctl status ai-assistant-worker"
echo "  Docker: docker compose ps"
echo ""
echo "Логи:"
echo "  Worker: tail -f logs/worker.log"
echo "  Bot: docker compose logs -f bot"
echo "  Redis: docker compose logs -f redis"