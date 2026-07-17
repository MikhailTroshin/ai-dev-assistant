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
    
    work_dir = Path(working_dir) if working_dir else settings.ML_REPO_PATH
    logger.info(f"Используем директорию: {work_dir}")
    
    logger.info("Запускаем Claude Code...")
    result = await claude_runner.run(
        prompt=prompt,
        working_dir=work_dir
    )
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    result.update({
        "task_id": task_id,
        "duration_seconds": duration,
        "started_at": start_time.isoformat(),
        "completed_at": end_time.isoformat()
    })
    
    logger.info(f"✅ Задача {task_id} завершена за {duration:.2f}с")
    logger.info(f"Success: {result['success']}")
    
    return result


# Функции для lifecycle - обычные async функции, НЕ staticmethod
async def startup(ctx):
    logger.info("🟢 Worker запущен")
    logger.info(f"Redis: {settings.REDIS_HOST}:{settings.REDIS_PORT}")


async def shutdown(ctx):
    logger.info("🔴 Worker остановлен")


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
    
    # Ссылаемся на функции модуля
    on_startup = startup
    on_shutdown = shutdown


async def main():
    """Тестовый запуск"""
    logger.info("Создаём пул Redis...")
    redis = await create_pool(WorkerSettings.redis_settings)
    
    logger.info("Добавляем задачу в очередь...")
    task = await redis.enqueue_job(
        'process_task',
        task_id="test-001",
        prompt="Объясни структуру проекта в текущей директории",
        working_dir=str(settings.ML_REPO_PATH)
    )
    
    logger.info(f"Задача добавлена: {task.job_id}")
    logger.info("Ожидаем результат (до 120с)...")
    
    try:
        result = await task.result(timeout=120)
        logger.info(f"Результат получен: {result}")
        print(f"\n✅ Результат:\n{result}")
    except asyncio.TimeoutError:
        logger.error("❌ Таймаут ожидания результата")
        print("❌ Таймаут - задача не выполнилась")
        raise


if __name__ == "__main__":
    asyncio.run(main())