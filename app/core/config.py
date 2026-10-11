from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./code_companion.db"
    LLM_API_KEY: str | None = None
    CORS_ORIGINS: str = "http://localhost:8000,http://127.0.0.1:8000"
    ENABLE_LOCAL_CODE_EXECUTION: bool = False
    CODE_EXECUTION_TIMEOUT_SECONDS: float = Field(default=3.0, gt=0, le=10)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()


def get_cors_origins() -> list[str]:
    return [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()]
