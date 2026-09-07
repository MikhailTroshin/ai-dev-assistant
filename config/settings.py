from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings
from pathlib import Path


class ProjectConfig(BaseSettings):
    """Конфигурация одного проекта (репозитория) продукта."""
    path: Path
    default: bool = False
    description: str = ""
    venv: Optional[Path] = None
    venv_activate: str = ""
    test_cmd: str = ""
    related: list[str] = []

    @field_validator("related")
    @classmethod
    def _check_related(cls, v: list[str]) -> list[str]:
        for name in v:
            if name not in settings.PROJECTS:
                raise ValueError(f"Неизвестный связанный проект: {name}")
        return v


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
    CLAUDE_TIMEOUT: int = 600  # 10 минут
    
    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///data/assistant.db"
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE: Path = Path("logs/assistant.log")
    
    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ADMIN_ID: int = 0
    
    # Task timeouts
    TASK_TIMEOUT: int = 900  # 15 минут
    POLL_INTERVAL: int = 5   # Проверка каждые 5 секунд
    
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
