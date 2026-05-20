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
    database_url: str = Field(default="", alias="DATABASE_URL")   # Neon PostgreSQL URL; falls back to SQLite
    chroma_path: str = Field(default="./chroma_db", alias="FINCOACH_CHROMA_PATH")

    # Behavior flags
    demo_mode: bool = Field(default=False, alias="FINCOACH_DEMO_MODE")

    # Admin allowlist (comma-separated usernames). Empty = admin endpoints disabled.
    admin_usernames: str = Field(default="", alias="FINCOACH_ADMIN_USERNAMES")

    # Auth
    jwt_secret: str = Field(default="dev-secret-change-me-in-production", alias="FINCOACH_JWT_SECRET")
    jwt_algorithm: str = "HS256"
    jwt_ttl_seconds: int = Field(default=60 * 60 * 24 * 30, alias="FINCOACH_JWT_TTL_SECONDS")  # 30 days

    # LLM
    # Locked to Gemini 3.1 Flash-Lite for cheapest multimodal inference ($0.25 / 1M input).
    # All roles (chat / vision / extract) use the same model.
    gemini_model: str = Field(default="gemini-3.1-flash-lite", alias="GEMINI_MODEL")
    gemini_vision_model: str = Field(
        default="gemini-3.1-flash-lite", alias="GEMINI_VISION_MODEL",
        description="Model for PDF/image vision dump.",
    )
    gemini_extract_model: str = Field(
        default="gemini-3.1-flash-lite", alias="GEMINI_EXTRACT_MODEL",
        description="Model for text-only schema extraction.",
    )
    gemini_temperature: float = Field(default=0.3, alias="GEMINI_TEMPERATURE")

    @property
    def vision_model(self) -> str:
        return self.gemini_vision_model or self.gemini_model

    @property
    def extract_model(self) -> str:
        return self.gemini_extract_model or self.gemini_model

    # LangSmith tracing
    langsmith_tracing: bool = Field(default=False, alias="LANGSMITH_TRACING")
    langsmith_project: str = Field(default="fincoach-hackathon", alias="LANGSMITH_PROJECT")

    @property
    def using_postgres(self) -> bool:
        return bool(self.database_url and self.database_url.startswith("postgresql"))

    @property
    def db_url(self) -> str:
        if self.using_postgres:
            # SQLAlchemy needs psycopg2 driver prefix for sync engine
            url = self.database_url
            if url.startswith("postgresql://") and "+psycopg2" not in url:
                url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
            return url
        return f"sqlite:///{self.db_path}"

    @property
    def checkpointer_url(self) -> str:
        """URL for LangGraph AsyncPostgresSaver (psycopg3 format)."""
        if self.using_postgres:
            # psycopg3 expects plain postgresql:// (no driver prefix)
            url = self.database_url
            if "+psycopg2" in url:
                url = url.replace("+psycopg2", "")
            return url
        return self.db_path  # SQLite path for AsyncSqliteSaver


settings = Settings()


def configure_langsmith() -> None:
    """Wire LangSmith env vars so LangChain auto-traces when enabled."""
    if settings.langsmith_tracing and settings.langsmith_api_key:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
