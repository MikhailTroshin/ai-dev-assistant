import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from arq import create_pool
from arq.connections import RedisSettings

from src.core.claude_runner import claude_runner
from config.settings import settings

# Настраиваем логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def process_task(
    ctx: dict,
    task_id: str,
    prompt: str,
    working_dir: Optional[str] = None
) -> dict:
    """Обработчик задач из очереди"""
    logger.info(f"🚀 ПОЛУЧЕНА ЗАДАЧА {task_id}")
    logger.info(f"Промпт: {prompt[:100]}...")
    logger.info(f"Рабочая директория: {working_dir}")
    
    start_time = datetime.now()
    
    # Определяем рабочую директорию
    work_dir = Path(working_dir) if working_dir else settings.ML_REPO_PATH
    logger.info(f"Используем директорию: {work_dir}")
    
    # Запускаем Claude Code
    logger.info("Запускаем Claude Code...")
    result = await claude_runner.run(
        prompt=prompt,
        working_dir=work_dir
    )
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    # Добавляем метаданные
    result.update({
        "task_id": task_id,
        "duration_seconds": duration,
        "started_at": start_time.isoformat(),
        "completed_at": end_time.isoformat()
    })
    
    logger.info(f"✅ Задача {task_id} завершена за {duration:.2f}с")
    logger.info(f"Success: {result['success']}")
    
    return result


class WorkerSettings:
    """Настройки для arq worker"""
    
    functions = [process_task]
    
    redis_settings = RedisSettings(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        database=settings.REDIS_DB
    )
    
    max_jobs = 1
    job_timeout = 300
    
    @staticmethod
    async def on_startup(ctx):
        logger.info("🟢 Worker запущен")
        logger.info(f"Redis: {settings.REDIS_HOST}:{settings.REDIS_PORT}")
    
    @staticmethod
    async def on_shutdown(ctx):
        logger.info("🔴 Worker остановлен")


async def main():
    """Тестовый запуск"""
    logger.info("Создаём пул Redis...")
    redis = await create_pool(WorkerSettings.redis_settings)
    
    logger.info("Добавляем задачу в очередь...")
    task = await redis.enqueue_job(
        'process_task',
        task_id="test-001",
        prompt="Кратко опиши структуру текещего репозитория",
        working_dir=str(settings.ML_REPO_PATH)
    )
    
    logger.info(f"Задача добавлена: {task.job_id}")
    logger.info("Ожидаем результат (до 120с)...")
    
    try:
        result = await task.result(timeout=120)
        logger.info(f"\n✅ Результат получен: {result}")
    except asyncio.TimeoutError:
        logger.error("❌ Таймаут ожидания результата")
        raise


if __name__ == "__main__":
    asyncio.run(main())
