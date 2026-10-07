from typing import Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from pathlib import Path


class ProjectConfig(BaseModel):
    """Конфигурация одного проекта (репозитория) продукта."""
    path: Path
    default: bool = False
    description: str = ""
    # Виртуальная среда для запуска кода/тестов (папка venv)
    venv: Optional[Path] = None
    # Произвольная команда активации среды (например, conda) — используется,
    # если venv не подходит.
    venv_activate: str = ""
    # Команда запуска тестов в этом репо
    test_cmd: str = ""
    # Проекты, напрямую связанные с этим (соседи по графу зависимостей)
    related: list[str] = []

    @property
    def python_bin(self) -> Optional[Path]:
        """Путь до python-интерпретатора в venv (None, если venv не задан)."""
        if self.venv is None:
            return None
        return self.venv / "bin" / "python"


class Settings(BaseSettings):
    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    
    # Paths
    PROJECT_PATH: Path = Path("/home/ws/mtroshin/ai_assistant")
    ML_REPO_PATH: Path = Path("/home/ws/mtroshin/ragllm")

    # Реестр проектов продукта (мульти-репо)
    PROJECTS: dict[str, ProjectConfig] = Field(
        default={
            "ragllm": ProjectConfig(
                path=Path("/home/ws/mtroshin/ragllm"),
                default=True,
                description="RAGLLM. Основная Python-часть проекта ASKAI. Реализует backend продукта",
                venv=Path("/home/ws/mtroshin/ragllm/.venv"),
                test_cmd="pytest tests/",
                related=["askai"],
            ),
            "askai": ProjectConfig(
                path=Path("/home/ws/mtroshin/reps/askai"),
                default=False,
                description="ASKAI. Java-часть проекта ASKAI. Реализует фронтенд продукта",
                test_cmd="mvn test",
                related=["ragllm"],
            ),
            "eruditeML": ProjectConfig(
                path=Path("/home/ws/mtroshin/reps/eruditeml"),
                default=False,
                description="ML-сервисы для проекта Эрудит",
                related=["eruditeML_torch"],
            ),
            "eruditeML_torch": ProjectConfig(
                path=Path("/home/ws/mtroshin/EruditeML_Torch"),
                default=False,
                description="ML-сервисы для проекта Эрудит (PyTorch-версия)",
                related=["levitan"],
            ),
            "levitan": ProjectConfig(
                path=Path("/home/ws/mtroshin/reps/levitan"),
                default=False,
                description="Levitan",
                related=["eruditeML_torch"],
            ),
            "infra": ProjectConfig(
                path=Path("/home/ws/mtroshin/ai_assistant"),
                default=False,
                description="Инфраструктура AI-ассистента",
            ),
        }
    )
    
    # Claude Code
    CLAUDE_CODE_PATH: str = "claude"
    # Таймаут по умолчанию для одной задачи Claude Code (сек)
    CLAUDE_TIMEOUT: int = 600  # 10 минут
    # Таймауты по командам (сек). Разработка/ревью больших MR идут долго,
    # вопросы — быстро. Внутренний таймаут всегда = значение команды минус
    # CLAUDE_TIMEOUT_MARGIN (запас, чтобы результат успел сохраниться в
    # Redis до того, как arq отменит джобу).
    COMMAND_TIMEOUTS: dict[str, int] = Field(
        default={
            "ask": 600,
            "task": 3600,        # разработка по Jira-задаче — до часа
            "bug": 1800,
            "code-review": 1800,
            "rebase": 1800,
            "reply": 1800,       # ответ в диалоге (продолжение задачи)
        }
    )
    # Запас между внутренним таймаутом Claude и таймаутом arq-джобы (сек):
    # за это время результат должен успеть записаться в БД и Redis
    CLAUDE_TIMEOUT_MARGIN: int = 60
    
    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///data/assistant.db"
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE: Path = Path("logs/assistant.log")
    
    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ADMIN_ID: int = 0
    
    # Task timeouts
    TASK_TIMEOUT: int = 3900  # верхняя граница arq для любой задачи (макс. command timeout + margin)
    POLL_INTERVAL: int = 5   # Проверка каждые 5 секунд


def get_command_timeout(command: str | None) -> int:
    """Таймаут Claude-запуска для команды (task=1ч, ask=10мин и т.д.)."""
    if command and command in settings.COMMAND_TIMEOUTS:
        return settings.COMMAND_TIMEOUTS[command]
    return settings.CLAUDE_TIMEOUT


def get_job_timeout(command: str | None) -> int:
    """Таймаут arq-джобы: внутренний таймаут + запас на сохранение результата."""
    return get_command_timeout(command) + settings.CLAUDE_TIMEOUT_MARGIN
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()


def get_default_project() -> str:
    """Имя проекта по умолчанию (первый с default=True, иначе первый из реестра)."""
    for name, cfg in settings.PROJECTS.items():
        if cfg.default:
            return name
    return next(iter(settings.PROJECTS))


def get_project_path(project: str | None) -> Path:
    """Путь до репозитория проекта. Unknown → дефолтный проект."""
    if project and project in settings.PROJECTS:
        return settings.PROJECTS[project].path
    return settings.PROJECTS[get_default_project()].path


def validate_relations() -> list[str]:
    """Проверяет, что все related-ссылки указывают на существующие проекты."""
    errors = []
    for name, cfg in settings.PROJECTS.items():
        for related_name in cfg.related:
            if related_name not in settings.PROJECTS:
                errors.append(f"{name}: неизвестный related-проект '{related_name}'")
    return errors
