"""Application settings loaded from environment / .env file."""
from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API keys
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    news_api_key: str = Field(default="", alias="NEWS_API_KEY")
    langsmith_api_key: str = Field(default="", alias="LANGSMITH_API_KEY")

    # Server
    port: int = Field(default=8765, alias="FINCOACH_PORT")

    # Storage
    db_path: str = Field(default="./fincoach.db", alias="FINCOACH_DB_PATH")
    chroma_path: str = Field(default="./chroma_db", alias="FINCOACH_CHROMA_PATH")

    # Behavior flags
    demo_mode: bool = Field(default=False, alias="FINCOACH_DEMO_MODE")

    # LLM
    gemini_model: str = Field(default="gemini-2.0-flash", alias="GEMINI_MODEL")
    gemini_temperature: float = Field(default=0.3, alias="GEMINI_TEMPERATURE")

    # LangSmith tracing
    langsmith_tracing: bool = Field(default=False, alias="LANGSMITH_TRACING")
    langsmith_project: str = Field(default="fincoach-hackathon", alias="LANGSMITH_PROJECT")

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"


settings = Settings()


def configure_langsmith() -> None:
    """Wire LangSmith env vars so LangChain auto-traces when enabled."""
    if settings.langsmith_tracing and settings.langsmith_api_key:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
