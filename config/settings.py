from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    
    # Paths
    PROJECT_PATH: Path = Path("/home/ws/mtroshin/ai_assistant")
    ML_REPO_PATH: Path = Path("/home/ws/mtroshin/ragllm")
    
    # Claude Code
    CLAUDE_CODE_PATH: str = "claude"
    
    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///data/assistant.db"
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE: Path = Path("logs/assistant.log")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
