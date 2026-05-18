"""Shared fixtures for the backend test suite.

`client` gives every test a fresh FastAPI TestClient backed by a temp SQLite
file. It auto-registers a demo user via `/auth/register`, then patches the
profile so the seeded shape (id=1, name="Demo User", risk_profile="balanced")
matches what the tests assert. Every request the client issues carries the
bearer token by default — tests written before auth was added don't need
to change.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("FINCOACH_DB_PATH", str(db_file))

    # Force settings + db modules to re-read the env var.
    # Also reload every module that captured a `SessionLocal` reference at
    # import time, otherwise the routers keep talking to the previous test's DB.
    import importlib
    import sys

    from app import settings as settings_mod

    importlib.reload(settings_mod)
    from app.db import session as session_mod

    importlib.reload(session_mod)
    session_mod.init_db()

    for mod_name in list(sys.modules):
        if (
            mod_name.startswith("app.routers.")
            or mod_name.startswith("app.tools.")
            or mod_name.startswith("app.auth.")
        ):
            importlib.reload(sys.modules[mod_name])

    from app import main as main_mod

    importlib.reload(main_mod)

    from fastapi.testclient import TestClient

    with TestClient(main_mod.app) as c:
        # Register a default user (id=1) and bake the bearer token into every
        # subsequent request. Profile is patched to the legacy "Demo User"
        # shape expected by pre-auth tests.
        reg = c.post(
            "/auth/register",
            json={"username": "demo", "password": "demopass"},
        )
        assert reg.status_code == 201, reg.text
        token = reg.json()["token"]
        c.headers.update({"Authorization": f"Bearer {token}"})
        patch = c.patch(
            "/profile",
            json={"name": "Demo User", "risk_profile": "balanced"},
        )
        assert patch.status_code == 200, patch.text
        yield c


@pytest.fixture
def has_gemini_key() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))
