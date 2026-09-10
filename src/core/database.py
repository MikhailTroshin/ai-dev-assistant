import logging
from datetime import datetime
from typing import Optional, List
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker

from config.settings import settings

logger = logging.getLogger(__name__)

Base = declarative_base()


class TaskRecord(Base):
    """Запись о выполненной задаче"""
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(255), unique=True, index=True)
    user_id = Column(Integer, index=True)
    chat_id = Column(Integer, index=True)
    command = Column(String(50))  # ask, task, bug, code-review, rebase
    prompt = Column(Text)
    result = Column(Text)
    success = Column(Boolean)
    error = Column(Text, nullable=True)
    duration_seconds = Column(Float)
    tokens_used = Column(Integer, nullable=True)
    project = Column(String(100), nullable=True)  # имя проекта из реестра PROJECTS
    logs = Column(Text, nullable=True)  # технический лог выполнения (диагностика ошибок)
    notified = Column(Boolean, default=False, nullable=False)  # отправлено ли уведомление о потере задачи
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    def __repr__(self):
        return f"<Task {self.task_id}: {self.command} ({'OK' if self.success else 'FAIL'})>"


class Database:
    """Управление базой данных"""
    
    def __init__(self):
        self.engine = create_async_engine(
            settings.DATABASE_URL,
            echo=False
        )
        self.async_session = sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
    
    async def init_db(self):
        """Создать таблицы и применить миграции"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Миграция: колонка project (SQLite не поддерживает ADD COLUMN IF NOT EXISTS)
            columns = await conn.execute(text("PRAGMA table_info(tasks)"))
            existing = {row[1] for row in columns.fetchall()}
            if "project" not in existing:
                await conn.execute(text("ALTER TABLE tasks ADD COLUMN project VARCHAR(100)"))
                logger.info("Миграция: добавлена колонка tasks.project")
            if "logs" not in existing:
                await conn.execute(text("ALTER TABLE tasks ADD COLUMN logs TEXT"))
                logger.info("Миграция: добавлена колонка tasks.logs")
            if "notified" not in existing:
                await conn.execute(text("ALTER TABLE tasks ADD COLUMN notified BOOLEAN DEFAULT 0 NOT NULL"))
                logger.info("Миграция: добавлена колонка tasks.notified")
        logger.info("База данных инициализирована")
    
    async def save_task(self, task_data: dict) -> TaskRecord:
        """Сохранить задачу"""
        async with self.async_session() as session:
            task = TaskRecord(**task_data)
            session.add(task)
            await session.commit()
            await session.refresh(task)
            logger.info(f"Задача {task.task_id} сохранена в БД")
            return task
    
    async def update_task(self, task_id: str, update_data: dict) -> Optional[TaskRecord]:
        """Обновить задачу"""
        async with self.async_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(TaskRecord).where(TaskRecord.task_id == task_id)
            )
            task = result.scalar_one_or_none()
            
            if task:
                for key, value in update_data.items():
                    setattr(task, key, value)
                await session.commit()
                await session.refresh(task)
                return task
            return None
    
    async def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """Получить задачу по ID"""
        async with self.async_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(TaskRecord).where(TaskRecord.task_id == task_id)
            )
            return result.scalar_one_or_none()
    
    async def get_user_tasks(self, user_id: int, limit: int = 10) -> List[TaskRecord]:
        """Получить задачи пользователя"""
        async with self.async_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(TaskRecord)
                .where(TaskRecord.user_id == user_id)
                .order_by(TaskRecord.created_at.desc())
                .limit(limit)
            )
            return result.scalars().all()

    async def get_stale_tasks(self, cutoff: datetime, limit: int = 10) -> List[TaskRecord]:
        """
        Незавершённые задачи (completed_at IS NULL), созданные раньше cutoff
        и ещё не помеченные уведомлёнными. Бот использует это для детекта
        потерянных задач (worker упал до сохранения результата).
        """
        async with self.async_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(TaskRecord)
                .where(
                    TaskRecord.completed_at.is_(None),
                    TaskRecord.created_at < cutoff,
                    TaskRecord.notified.is_(False),
                )
                .order_by(TaskRecord.created_at.asc())
                .limit(limit)
            )
            return result.scalars().all()

    async def mark_task_notified(self, task_id: str, error: Optional[str] = None) -> None:
        """Пометить задачу как уведомлённую (защита от повторных сообщений о потере)."""
        update_data = {"notified": True}
        if error:
            update_data["error"] = error
            update_data["success"] = False
        await self.update_task(task_id, update_data)
    
    async def get_stats(self) -> dict:
        """Получить статистику"""
        async with self.async_session() as session:
            from sqlalchemy import select, func
            
            # Всего задач
            total = await session.execute(select(func.count(TaskRecord.id)))
            total_count = total.scalar()
            
            # Успешных
            success = await session.execute(
                select(func.count(TaskRecord.id)).where(TaskRecord.success == True)
            )
            success_count = success.scalar()
            
            # Среднее время
            avg_time = await session.execute(
                select(func.avg(TaskRecord.duration_seconds))
            )
            avg_duration = avg_time.scalar() or 0
            
            # По командам
            by_command = await session.execute(
                select(TaskRecord.command, func.count(TaskRecord.id))
                .group_by(TaskRecord.command)
            )
            command_stats = dict(by_command.all())
            
            return {
                "total": total_count,
                "success": success_count,
                "failed": total_count - success_count,
                "avg_duration": round(avg_duration, 2),
                "by_command": command_stats
            }


# Singleton
db = Database()