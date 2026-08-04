import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import redis.asyncio as redis
from arq import create_pool
from arq.connections import RedisSettings

from src.core.claude_runner import claude_runner
from src.core.database import db
from config.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def process_task(
    ctx: dict,
    task_id: str,
    prompt: str,
    working_dir: Optional[str] = None,
    chat_id: Optional[int] = None,
    user_id: Optional[int] = None,
    command: Optional[str] = None
) -> dict:
    """Обработчик задач из очереди"""
    logger.info(f"🚀 ПОЛУЧЕНА ЗАДАЧА {task_id}")
    logger.info(f"Промпт: {prompt[:100]}...")
    
    start_time = datetime.now()
    work_dir = Path(working_dir) if working_dir else settings.ML_REPO_PATH
    
    # Сохраняем начальную запись в БД
    await db.save_task({
        "task_id": task_id,
        "user_id": user_id,
        "chat_id": chat_id,
        "command": command or "unknown",
        "prompt": prompt,
        "result": None,
        "success": False,
        "error": None,
        "duration_seconds": 0,
        "created_at": start_time
    })
    
    # Запускаем Claude Code
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
        "completed_at": end_time.isoformat(),
        "chat_id": chat_id,
        "user_id": user_id
    })
    
    # Обновляем запись в БД
    await db.update_task(task_id, {
        "result": result.get("output", ""),
        "success": result.get("success", False),
        "error": result.get("error"),
        "duration_seconds": duration,
        "completed_at": end_time
    })
    
    logger.info(f"✅ Задача {task_id} завершена за {duration:.2f}с")
    
    # Сохраняем результат в Redis для бота
    if chat_id:
        redis_client = redis.from_url(
            f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
        )
        
        result_key = f"task_result:{task_id}"
        await redis_client.setex(
            result_key,
            3600,
            json.dumps(result)
        )
        
        await redis_client.sadd("pending_results", task_id)
        await redis_client.close()
    
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
    job_timeout = settings.TASK_TIMEOUT
    
    @staticmethod
    async def on_startup(ctx):
        logger.info("🟢 Worker запущен")
        await db.init_db()  # Инициализируем БД при старте


async def main():
    """Тестовый запуск"""
    await db.init_db()
    
    logger.info("Создаём пул Redis...")
    redis_pool = await create_pool(WorkerSettings.redis_settings)
    
    logger.info("Добавляем задачу в очередь...")
    task = await redis_pool.enqueue_job(
        'process_task',
        task_id="test-001",
        prompt="Объясни структуру проекта",
        working_dir=str(settings.ML_REPO_PATH),
        chat_id=123456,
        user_id=123456,
        command="test"
    )
    
    logger.info(f"Задача добавлена: {task.job_id}")
    
    try:
        result = await task.result(timeout=120)
        logger.info("✅ Результат получен")
    except asyncio.TimeoutError:
        logger.error("❌ Таймаут")
        raise


if __name__ == "__main__":
    asyncio.run(main())