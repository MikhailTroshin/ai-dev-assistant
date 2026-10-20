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
    session_id = Column(String(64), nullable=True, index=True)  # ID сессии Claude Code (для диалогов --resume)
    jira_key = Column(String(20), nullable=True, index=True)  # ключ Jira-задачи (AA-123), если запрос относится к ней
    parent_task_id = Column(String(255), nullable=True, index=True)  # task_id корневой задачи диалога (для reply-продолжений)
    jira_summary = Column(String(255), nullable=True)  # название Jira-задачи (для отображения на кнопках меню)
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
            if "session_id" not in existing:
                await conn.execute(text("ALTER TABLE tasks ADD COLUMN session_id VARCHAR(64)"))
                logger.info("Миграция: добавлена колонка tasks.session_id")
            if "jira_key" not in existing:
                await conn.execute(text("ALTER TABLE tasks ADD COLUMN jira_key VARCHAR(20)"))
                logger.info("Миграция: добавлена колонка tasks.jira_key")
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tasks_jira_key ON tasks (jira_key)"))
            if "parent_task_id" not in existing:
                await conn.execute(text("ALTER TABLE tasks ADD COLUMN parent_task_id VARCHAR(255)"))
                logger.info("Миграция: добавлена колонка tasks.parent_task_id")
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tasks_parent_task_id ON tasks (parent_task_id)"))
            if "jira_summary" not in existing:
                await conn.execute(text("ALTER TABLE tasks ADD COLUMN jira_summary VARCHAR(255)"))
                logger.info("Миграция: добавлена колонка tasks.jira_summary")
        await self._backfill_dialog_roots()
        logger.info("База данных инициализирована")

    async def _backfill_dialog_roots(self) -> None:
        """
        Разовая миграция данных: старые reply-задачи не имели parent_task_id.
        Все записи одной диалоговой цепочки делят один session_id — корнем
        назначаем самую раннюю задачу с этим session_id (её parent = сам корень).
        """
        async with self.async_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(TaskRecord).where(TaskRecord.parent_task_id.is_(None))
            )
            orphans = result.scalars().all()
            if not orphans:
                return

            # Группируем сирот по session_id
            by_session: dict[str, list[TaskRecord]] = {}
            for task in orphans:
                if task.session_id:
                    by_session.setdefault(task.session_id, []).append(task)

            updated = 0
            for session_id, group in by_session.items():
                # Корень — самая ранняя задача цепочки; все её элементы (включая
                # записи без jira_key) наследуют её parent_task_id и jira_key
                root = min(group, key=lambda t: t.created_at)
                updates = []
                if session_id in {t.session_id for t in group}:
                    # Вся цепочка: все задачи с этим session_id, не только сироты
                    pass
                chain = await session.execute(
                    select(TaskRecord).where(TaskRecord.session_id == session_id)
                )
                chain_tasks = chain.scalars().all()
                for task in chain_tasks:
                    task.parent_task_id = root.task_id
                    if root.jira_key and not task.jira_key:
                        task.jira_key = root.jira_key
                    updates.append(task)
                updated += len(updates)

            # Одиночные задачи без session_id — корень сами по себе
            for task in orphans:
                if not task.session_id:
                    task.parent_task_id = task.task_id
                    updated += 1

            await session.commit()
            if updated:
                logger.info(f"Миграция данных: parent_task_id проставлен для {updated} задач")
    
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

    async def get_recent_resumable_tasks(self, user_id: int, limit: int = 10) -> List[TaskRecord]:
        """
        Последние задачи пользователя, доступные для продолжения диалога
        (есть session_id). Дедупликация: на каждый диалог (parent_task_id или
        jira_key) — только свежайшая запись; старые цепочки без parent_task_id
        дедуплицируются по jira_key.
        """
        async with self.async_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(TaskRecord)
                .where(
                    TaskRecord.user_id == user_id,
                    TaskRecord.session_id.isnot(None),
                )
                .order_by(TaskRecord.created_at.desc())
                .limit(200)
            )
            tasks = result.scalars().all()

        seen_dialogs: set = set()
        selected: List[TaskRecord] = []
        for task in tasks:  # от свежих к старым
            key = task.parent_task_id or task.jira_key
            if key:
                if key in seen_dialogs:
                    continue
                seen_dialogs.add(key)
            selected.append(task)
            if len(selected) >= limit:
                break
        return selected

    async def get_tasks_missing_jira_summary(self, limit: int = 20) -> List[TaskRecord]:
        """Задачи с jira_key, у которых ещё не подтянуто название (jira_summary)."""
        async with self.async_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(TaskRecord)
                .where(
                    TaskRecord.jira_key.isnot(None),
                    TaskRecord.jira_summary.is_(None),
                )
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