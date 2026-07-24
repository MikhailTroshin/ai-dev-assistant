FROM python:3.12-slim

# Устанавливаем системные зависимости (git нужен для работы с репозиторием, curl для проверок)
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем исходный код
COPY . .

# Создаем директорию для данных и логов внутри контейнера
RUN mkdir -p /app/data /app/logs

# Команда по умолчанию (будет переопределена в docker-compose.yml)
CMD ["python", "-m", "src.bot.main"]