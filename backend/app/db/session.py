"""SQLAlchemy engine + session factory.

Supports both SQLite (local dev) and PostgreSQL (Neon, production).
The active backend is chosen by the DATABASE_URL env var.
"""
from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.settings import settings
from app.db.models import Base


def _make_engine():
    if settings.using_postgres:
        return create_engine(settings.db_url, echo=False, pool_pre_ping=True)
    # SQLite — single-file, needs check_same_thread disabled
    return create_engine(
        settings.db_url,
        echo=False,
        connect_args={"check_same_thread": False},
    )


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """Create tables. On PostgreSQL uses CREATE TABLE IF NOT EXISTS."""
    Base.metadata.create_all(engine)
    if not settings.using_postgres:
        _migrate_sqlite()


# SQLite-only lightweight in-place migrations (PostgreSQL uses create_all).
_PENDING_COLUMNS: list[tuple[str, str, str]] = [
    ("transaction", "source",          "VARCHAR(16) DEFAULT 'manual'"),
    ("transaction", "account_id",      "INTEGER"),
    ("transaction", "subscription_id", "INTEGER"),
    ("subscription", "direction",      "VARCHAR(8) DEFAULT 'expense'"),
    ("goal",         "currency",       "VARCHAR(8) DEFAULT 'TRY'"),
    ("holding",      "currency",       "VARCHAR(8) NOT NULL DEFAULT 'USD'"),
]


def _migrate_sqlite() -> None:
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, column, ddl in _PENDING_COLUMNS:
            if not insp.has_table(table):
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            if column in existing:
                continue
            conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {column} {ddl}'))


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
