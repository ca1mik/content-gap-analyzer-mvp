import os
from functools import lru_cache

from pydantic import BaseModel, Field


class Settings(BaseModel):
    openai_api_key: str | None = Field(default=None)
    openai_base_url: str = Field(default="https://api.openai.com/v1")
    openai_model: str = Field(default="gpt-4.1-mini")
    http_timeout_seconds: float = Field(default=20.0)
    http_retries: int = Field(default=2)
    database_url: str = Field(default="sqlite:///./app.db")
    max_page_chars: int = Field(default=20_000)
    max_ai_overview_chars: int = Field(default=8_000)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            http_timeout_seconds=float(os.getenv("HTTP_TIMEOUT_SECONDS", "20")),
            http_retries=int(os.getenv("HTTP_RETRIES", "2")),
            database_url=os.getenv("DATABASE_URL", "sqlite:///./app.db"),
            max_page_chars=int(os.getenv("MAX_PAGE_CHARS", "20000")),
            max_ai_overview_chars=int(os.getenv("MAX_AI_OVERVIEW_CHARS", "8000")),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
