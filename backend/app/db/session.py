"""SQLAlchemy engine + session factory.

Supports both SQLite (local dev) and PostgreSQL (Neon, production).
The active backend is chosen by the DATABASE_URL env var.
"""
from __future__ import annotations

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
from app.settings import settings


def _make_engine():
    if settings.using_postgres:
        return create_engine(settings.db_url, echo=False, pool_pre_ping=True)
    # SQLite — single-file, needs check_same_thread disabled
    eng = create_engine(
        settings.db_url,
        echo=False,
        connect_args={"check_same_thread": False},
    )
    # WAL lets the background news poller write while request threads read
    # concurrently without "database is locked". busy_timeout makes the rare
    # writer-vs-writer contention wait rather than fail immediately.
    @event.listens_for(eng, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    return eng


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """Create tables, then add any columns missing on an existing DB.

    ``create_all`` only creates *new* tables; it never adds columns to a table
    that already exists. Alembic isn't wired, so we run a tiny idempotent
    in-place column migration — on BOTH SQLite (dev/Tauri) and PostgreSQL
    (Cloud Run/Neon). Without this, a column added to an existing table (e.g.
    ``user.tier``) is absent in prod and every query touching it 500s.
    """
    Base.metadata.create_all(engine)
    _migrate_inplace()


# Lightweight in-place column adds for existing DBs (both SQLite + Postgres).
# Each entry is (table, column, DDL). The DATETIME type is rewritten to
# TIMESTAMP on Postgres at execution time.
_PENDING_COLUMNS: list[tuple[str, str, str]] = [
    ("transaction", "source",          "VARCHAR(16) DEFAULT 'manual'"),
    ("transaction", "account_id",      "INTEGER"),
    ("transaction", "subscription_id", "INTEGER"),
    ("subscription", "direction",      "VARCHAR(8) DEFAULT 'expense'"),
    ("goal",         "currency",       "VARCHAR(8) DEFAULT 'TRY'"),
    ("holding",      "currency",       "VARCHAR(8) NOT NULL DEFAULT 'USD'"),
    ("user",         "tier",           "VARCHAR(16) NOT NULL DEFAULT 'free'"),
    ("user",         "consented_at",   "DATETIME"),
    ("user",         "consent_version", "VARCHAR(32)"),
]


def _migrate_inplace() -> None:
    insp = inspect(engine)
    is_pg = engine.dialect.name == "postgresql"
    with engine.begin() as conn:
        for table, column, ddl in _PENDING_COLUMNS:
            if not insp.has_table(table):
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            if column in existing:
                continue
            # Postgres has no DATETIME type — use TIMESTAMP there.
            ddl_sql = ddl.replace("DATETIME", "TIMESTAMP") if is_pg else ddl
            # table/column come only from the static _PENDING_COLUMNS list above
            # (never user input), but quote both identifiers anyway so this stays
            # injection-proof if that list is ever fed from config.
            conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl_sql}'))


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
