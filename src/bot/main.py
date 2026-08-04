import asyncio
import json
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage

import redis.asyncio as redis
from arq import create_pool
from arq.connections import RedisSettings

from config.settings import settings
from src.core.database import db
from src.bot.handlers import router, send_long_message

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def check_results(bot: Bot, redis_client: redis.Redis):
    """Фоновая задача для проверки готовых результатов"""
    while True:
        try:
            # Получаем список готовых задач
            pending_tasks = await redis_client.smembers("pending_results")
            
            for task_id_bytes in pending_tasks:
                task_id = task_id_bytes.decode('utf-8')
                
                # Получаем результат
                result_key = f"task_result:{task_id}"
                result_data = await redis_client.get(result_key)
                
                if result_data:
                    result = json.loads(result_data)
                    
                    # Получаем chat_id
                    chat_mapping = await redis_client.hget("task_chat_mapping", task_id)
                    if chat_mapping:
                        mapping = json.loads(chat_mapping)
                        chat_id = mapping["chat_id"]
                        
                        # Отправляем результат
                        try:
                            if result['success']:
                                text = f"✅ Результат:\n\n{result['output']}"
                            else:
                                text = f"❌ Ошибка:\n\n{result['error']}"
                            
                            # Используем send_long_message с bot
                            await send_long_message(bot, text, chat_id=chat_id)
                            
                            # Удаляем из очереди
                            await redis_client.srem("pending_results", task_id)
                            await redis_client.delete(result_key)
                            await redis_client.hdel("task_chat_mapping", task_id)
                            
                            logger.info(f"Результат отправлен для задачи {task_id}")
                            
                        except Exception as e:
                            logger.error(f"Ошибка отправки результата: {e}")
                
        except Exception as e:
            logger.error(f"Ошибка в check_results: {e}")
        
        await asyncio.sleep(settings.POLL_INTERVAL)


async def main():
    """Запуск бота"""
    logger.info("Запуск Telegram бота...")
    
    # Инициализируем базу данных
    await db.init_db()
    logger.info("База данных инициализирована")
    
    # Создаём бота
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    
    # Подключаемся к Redis для FSM
    redis_settings = RedisSettings(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        database=settings.REDIS_DB
    )
    
    # Создаём пул Redis для очереди
    redis_pool = await create_pool(redis_settings)
    
    # Создаём клиент Redis для фоновых задач
    redis_client = redis.from_url(
        f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
    )
    
    # Создаём хранилище для FSM
    storage = RedisStorage.from_url(
        f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
    )
    
    # Создаём диспетчер
    dp = Dispatcher(storage=storage)
    
    # Передаём зависимости в handlers через middleware
    @dp.update.outer_middleware
    async def inject_deps(handler, event, data):
        data['redis_pool'] = redis_pool
        data['bot'] = bot
        return await handler(event, data)
    
    # Подключаем роутер
    dp.include_router(router)
    
    # Запускаем фоновую задачу проверки результатов
    check_task = asyncio.create_task(check_results(bot, redis_client))
    
    logger.info("Бот запущен")
    
    try:
        # Запускаем polling
        await dp.start_polling(bot)
    finally:
        check_task.cancel()
        await bot.session.close()
        await redis_pool.close()
        await redis_client.close()


if __name__ == "__main__":
    asyncio.run(main())