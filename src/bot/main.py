import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage

from arq import create_pool
from arq.connections import RedisSettings

from config.settings import settings
from src.bot.handlers import router

# Настраиваем логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """Запуск бота"""
    logger.info("Запуск Telegram бота...")
    
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
    
    # Создаём хранилище для FSM
    storage = RedisStorage.from_url(
        f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
    )
    
    # Создаём диспетчер
    dp = Dispatcher(storage=storage)
    
    # Передаём redis_pool в handlers через middleware
    @dp.update.outer_middleware
    async def inject_redis_pool(handler, event, data):
        data['redis_pool'] = redis_pool
        return await handler(event, data)
    
    # Подключаем роутер
    dp.include_router(router)
    
    logger.info("Бот запущен")
    
    try:
        # Запускаем polling
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await redis_pool.close()


if __name__ == "__main__":
    asyncio.run(main())