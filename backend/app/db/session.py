"""SQLAlchemy engine + session factory."""
from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.settings import settings
from app.db.models import Base

engine = create_engine(
    settings.db_url,
    echo=False,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """Create tables on first launch. No seed user — accounts are created via /auth/register."""
    Base.metadata.create_all(engine)
    _migrate_inplace()


# Lightweight in-place schema migrations for SQLite dev DB. We only ever ADD
# columns — existing data is preserved. Each entry: (table, column, ddl_type
# with DEFAULT). Idempotent: skipped if the column already exists.
_PENDING_COLUMNS: list[tuple[str, str, str]] = [
    ("transaction", "source", "VARCHAR(16) DEFAULT 'manual'"),
    ("transaction", "account_id", "INTEGER"),
    ("transaction", "subscription_id", "INTEGER"),
    ("subscription", "direction", "VARCHAR(8) DEFAULT 'expense'"),
]


def _migrate_inplace() -> None:
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
