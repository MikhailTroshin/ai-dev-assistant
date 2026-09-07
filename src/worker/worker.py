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
from src.core.project_context import build_repo_context
from config.settings import settings, get_project_path, get_default_project

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
    command: Optional[str] = None,
    project: Optional[str] = None,
    extra_projects: Optional[list[str]] = None
) -> dict:
    """Обработчик задач из очереди"""
    logger.info(f"🚀 ПОЛУЧЕНА ЗАДАЧА {task_id} (project={project}, extra={extra_projects})")
    logger.info(f"Промпт: {prompt[:100]}...")

    start_time = datetime.now()
    project = project or get_default_project()
    work_dir = Path(working_dir) if working_dir else get_project_path(project)

    # Подмешиваем контекст репозиториев (связи, среды, тесты) в промпт.
    # Проекты, упомянутые в тексте промпта, автоматически включаются в контекст.
    full_prompt = prompt + build_repo_context(project, extra_projects, prompt_text=prompt)

    # Сохраняем начальную запись в БД
    await db.save_task({
        "task_id": task_id,
        "user_id": user_id,
        "chat_id": chat_id,
        "command": command or "unknown",
        "prompt": full_prompt,
        "result": None,
        "success": False,
        "error": None,
        "duration_seconds": 0,
        "project": project,
        "created_at": start_time
    })

    # Запускаем Claude Code
    logger.info(f"Запускаем Claude Code в {work_dir}...")
    result = await claude_runner.run(
        prompt=full_prompt,
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

    # Лог выполнения: служебная информация + лог Claude Code
    run_logs = result.get("logs", "")
    worker_log = (
        f"task_id: {task_id}\n"
        f"command: {command}\n"
        f"project: {project}\n"
        f"working_dir: {work_dir}\n"
        f"prompt_len: {len(full_prompt)}\n"
        f"timed_out: {result.get('timed_out', False)}\n"
    )
    full_logs = worker_log + run_logs

    # Обновляем запись в БД (логи — всегда, даже при ошибке)
    await db.update_task(task_id, {
        "result": result.get("output", ""),
        "success": result.get("success", False),
        "error": result.get("error"),
        "duration_seconds": duration,
        "completed_at": end_time,
        "logs": full_logs,
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
            json.dumps({
                "success": result.get("success", False),
                "output": result.get("output", ""),
                "error": result.get("error"),
                "timed_out": result.get("timed_out", False),
                "task_id": task_id,
            })
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
        from config.settings import validate_relations
        errors = validate_relations()
        if errors:
            logger.error(f"❌ Ошибки в реестре проектов: {errors}")
            raise RuntimeError(f"Некорректная конфигурация PROJECTS: {errors}")
        await db.init_db()  # Инициализируем БД при старте


async def main():
    """Тестовый запуск"""
    await db.init_db()
    
    logger.info("Создаём пул Redis...")
    redis_pool = await create_pool(WorkerSettings.redis_settings)
    
    logger.info("Добавляем задачу в очередь...")
    import uuid
    task = await redis_pool.enqueue_job(
        'process_task',
        task_id=f"test-{uuid.uuid4().hex[:8]}",
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