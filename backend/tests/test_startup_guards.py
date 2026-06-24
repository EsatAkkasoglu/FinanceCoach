"""Startup safety guards in the FastAPI lifespan.

The happy local-startup path (default JWT secret, no K_SERVICE) is already
exercised by every test that uses the `client` fixture — it boots the full
lifespan via TestClient. Here we only assert the Cloud Run fail-fast guard.
"""
from __future__ import annotations

import pytest

from app.settings import DEFAULT_JWT_SECRET


async def test_cloud_run_with_default_jwt_secret_refuses_startup(monkeypatch):
    """On Cloud Run, booting with the public dev JWT secret must fail loudly
    (the guard runs before init_db, so no DB/supervisor side effects)."""
    monkeypatch.setenv("K_SERVICE", "fincoach-backend")  # → settings.is_cloud_run

    from app import main as main_mod

    # Patch the exact settings object the lifespan reads, so the test is robust
    # to module reloads done by other fixtures.
    monkeypatch.setattr(main_mod.settings, "jwt_secret", DEFAULT_JWT_SECRET)

    with pytest.raises(RuntimeError, match="FINCOACH_JWT_SECRET"):
        async with main_mod.lifespan(main_mod.app):
            pass
