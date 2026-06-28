"""Hermetic tests for the propose → approve/reject trade-target lifecycle and
the generalized upsert (asset class, PENDING status, horizon-keyed supersede).

All run against a shared in-memory SQLite DB — no network, no fincoach.db."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, TradeStatus, TradeTarget
from app.routers import crypto as crypto_router
from app.services.trade_targets import upsert_target_from_plan


@pytest.fixture()
def mem_sessionmaker():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _plan_result(direction="long", target=103.0, *, ticker="BTC-USD", symbol="BTC",
                 asset_class="crypto", horizon_hours=4):
    return {
        "ok": True,
        "rationale": "test thesis",
        "data": {
            "ticker": ticker, "symbol": symbol, "asset_class": asset_class,
            "direction": direction, "entry": 100.0, "target": target, "stop": 98.0,
            "target_pct": 3.0, "stop_pct": -2.0, "rr": 1.5,
            "confidence": 0.5, "score": 0.4, "horizon_hours": horizon_hours,
        },
    }


# ── generalized upsert ───────────────────────────────────────────────────────


def test_upsert_pending_status_and_asset_class(mem_sessionmaker):
    with mem_sessionmaker() as db:
        t = upsert_target_from_plan(
            db, 1, _plan_result(ticker="AAPL", symbol="AAPL", asset_class="stock"),
            status=TradeStatus.PENDING.value,
        )
        db.commit()
        assert t.status == TradeStatus.PENDING.value
        assert t.asset_class == "stock" and t.ticker == "AAPL"


def test_supersede_is_horizon_keyed(mem_sessionmaker):
    sm = mem_sessionmaker
    with sm() as db:
        upsert_target_from_plan(db, 1, _plan_result(target=103.0, horizon_hours=4))
        upsert_target_from_plan(db, 1, _plan_result(target=120.0, horizon_hours=168))
        db.commit()
        # A 4h re-scan must NOT wipe the 168h position.
        upsert_target_from_plan(db, 1, _plan_result(target=105.0, horizon_hours=4))
        db.commit()
        rows = db.query(TradeTarget).filter_by(user_id=1, ticker="BTC-USD").all()
        by_h = {r.horizon_hours: r for r in rows}
        assert set(by_h) == {4, 168}
        assert by_h[4].target_price == 105.0   # 4h replaced
        assert by_h[168].target_price == 120.0  # 168h untouched


def test_pending_is_superseded_by_a_fresh_pending(mem_sessionmaker):
    sm = mem_sessionmaker
    with sm() as db:
        upsert_target_from_plan(db, 1, _plan_result(target=103.0), status=TradeStatus.PENDING.value)
        db.commit()
        upsert_target_from_plan(db, 1, _plan_result(target=109.0), status=TradeStatus.PENDING.value)
        db.commit()
        pending = db.query(TradeTarget).filter_by(
            user_id=1, ticker="BTC-USD", status=TradeStatus.PENDING.value
        ).all()
        assert len(pending) == 1 and pending[0].target_price == 109.0


# ── confirm / reject endpoints (SessionLocal monkeypatched) ──────────────────


@pytest.fixture()
def patched_router(mem_sessionmaker, monkeypatch):
    monkeypatch.setattr(crypto_router, "SessionLocal", mem_sessionmaker)
    monkeypatch.setattr(crypto_router, "_live_price", lambda *a, **k: 101.0)
    return crypto_router


def _seed_pending(sm, **kw):
    with sm() as db:
        t = upsert_target_from_plan(db, 1, _plan_result(**kw), status=TradeStatus.PENDING.value)
        db.commit()
        return t.id


def test_confirm_flips_pending_to_active(patched_router, mem_sessionmaker):
    tid = _seed_pending(mem_sessionmaker)
    out = patched_router.confirm_target(tid, user_id=1)
    assert out["ok"] and out["confirmed"]
    assert out["target"]["status"] == "active"
    with mem_sessionmaker() as db:
        row = db.get(TradeTarget, tid)
        assert row.status == TradeStatus.ACTIVE.value
        assert row.expires_at is not None


def test_confirm_rejects_non_pending(patched_router, mem_sessionmaker):
    tid = _seed_pending(mem_sessionmaker)
    patched_router.confirm_target(tid, user_id=1)            # now ACTIVE
    again = patched_router.confirm_target(tid, user_id=1)    # second confirm
    assert again["ok"] is False and "not pending" in again["error"]


def test_confirm_is_owner_scoped(patched_router, mem_sessionmaker):
    tid = _seed_pending(mem_sessionmaker)
    out = patched_router.confirm_target(tid, user_id=999)
    assert out["ok"] is False and "not found" in out["error"]


def test_reject_marks_rejected(patched_router, mem_sessionmaker):
    tid = _seed_pending(mem_sessionmaker)
    out = patched_router.reject_target(tid, user_id=1)
    assert out["ok"] and out["rejected"]
    with mem_sessionmaker() as db:
        assert db.get(TradeTarget, tid).status == TradeStatus.REJECTED.value


def test_confirm_supersedes_other_active_same_horizon(patched_router, mem_sessionmaker):
    sm = mem_sessionmaker
    with sm() as db:
        active = upsert_target_from_plan(db, 1, _plan_result(target=103.0))  # ACTIVE 4h
        db.commit()
        active_id = active.id
    tid = _seed_pending(sm, target=110.0)  # PENDING 4h, same ticker
    patched_router.confirm_target(tid, user_id=1)
    with sm() as db:
        assert db.get(TradeTarget, active_id) is None       # old ACTIVE dropped
        assert db.get(TradeTarget, tid).status == TradeStatus.ACTIVE.value
