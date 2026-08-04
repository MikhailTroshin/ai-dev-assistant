#!/bin/bash

echo "🛑 Остановка AI Assistant..."

# Останавливаем Worker
echo "⚙️ Останавливаем Worker..."
sudo systemctl stop ai-assistant-worker

# Останавливаем Docker
echo "📦 Останавливаем Docker..."
docker compose down

echo "✅ Система остановлена"