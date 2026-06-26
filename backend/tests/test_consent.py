"""KVKK provable consent: recorded at register and via POST /account/consent."""
from __future__ import annotations

from app.services.consent import CURRENT_CONSENT_VERSION


def _consent_row(username: str):
    from sqlalchemy import select

    from app.db.models import User
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        return db.execute(
            select(User.consented_at, User.consent_version).where(User.username == username)
        ).one()


def test_register_records_consent_when_accepted(client):
    r = client.post(
        "/auth/register",
        json={"username": "consenter", "password": "secret1", "accept_terms": True},
    )
    assert r.status_code == 201, r.text
    body = r.json()["user"]
    assert body["consented"] is True
    assert body["consent_version"] == CURRENT_CONSENT_VERSION
    assert body["consent_current"] is True

    consented_at, version = _consent_row("consenter")
    assert consented_at is not None
    assert version == CURRENT_CONSENT_VERSION


def test_register_without_consent_leaves_it_null(client):
    r = client.post(
        "/auth/register",
        json={"username": "noconsent", "password": "secret1"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["user"]["consented"] is False
    consented_at, version = _consent_row("noconsent")
    assert consented_at is None and version is None


def test_post_consent_stamps_current_user(client):
    # The fixture's default user (id=1) registered without consent.
    me = client.get("/auth/me").json()
    assert me["consented"] is False

    r = client.post("/account/consent")
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["consented"] is True
    assert state["consent_version"] == CURRENT_CONSENT_VERSION

    assert client.get("/auth/me").json()["consented"] is True


def test_consent_requires_auth(client):
    r = client.post("/account/consent", headers={"Authorization": ""})
    assert r.status_code == 401
