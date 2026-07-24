#!/bin/bash

echo "🛑 Остановка AI Assistant..."

# Останавливаем Docker контейнеры
echo "📦 Останавливаем Docker..."
docker compose down

# Останавливаем Worker
echo "⚙️ Останавливаем Worker..."
pkill -f "arq src.worker.worker.WorkerSettings"

echo "✅ Система остановлена"