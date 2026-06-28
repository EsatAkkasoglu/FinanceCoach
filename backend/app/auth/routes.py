"""/auth/register, /auth/login, /auth/me, /auth/firebase, /auth/demo."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.deps import get_current_user
from app.auth.firebase_verify import decode_firebase_token
from app.auth.ratelimit import rate_limit
from app.auth.security import create_token, hash_password, verify_password
from app.db.models import Account, Goal, Holding, Subscription, Transaction, User
from app.db.session import SessionLocal
from app.services.consent import CURRENT_CONSENT_VERSION, consent_state

log = logging.getLogger("fincoach.auth")
router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=128)


class RegisterRequest(Credentials):
    # KVKK consent captured at sign-up. Optional for backward compat (demo/tests
    # that predate consent); the UI always sends True and gates submission on it.
    accept_terms: bool = Field(default=False)


class AuthResponse(BaseModel):
    token: str
    user: dict


def _user_dict(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "name": u.name,
        "avatar": u.avatar,
        "has_onboarded": bool(u.name),
        **consent_state(u),
    }


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, _rl: None = Depends(rate_limit("register", limit=5))):
    username = payload.username.strip().lower()
    if not USERNAME_RE.match(username):
        raise HTTPException(400, "username may only contain letters, digits, _ . -")

    with SessionLocal() as db:
        user = User(
            username=username,
            password_hash=hash_password(payload.password),
            name="",
        )
        # Stamp KVKK consent atomically with account creation when accepted.
        if payload.accept_terms:
            user.consented_at = datetime.utcnow()
            user.consent_version = CURRENT_CONSENT_VERSION
        db.add(user)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "username already taken") from exc
        db.refresh(user)
        token = create_token(user.id, user.username)
        return AuthResponse(token=token, user=_user_dict(user))


@router.post("/login", response_model=AuthResponse)
def login(payload: Credentials, _rl: None = Depends(rate_limit("login", limit=10))):
    username = payload.username.strip().lower()
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if user is None or not verify_password(payload.password, user.password_hash):
            raise HTTPException(401, "invalid username or password")
        token = create_token(user.id, user.username)
        return AuthResponse(token=token, user=_user_dict(user))


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return _user_dict(user)


def _seed_crypto_basket(db, user_id: int) -> None:
    """Best-effort: seed the curated crypto basket + 4-hour targets for a user.

    Runs on demo login (idempotent — skipped once the user has any target). Each
    basket coin gets a ~$1.5k notional holding entered at the live signal price
    and an ACTIVE 4-hour ``TradeTarget`` so the demo account shows concrete,
    risk-defined trades a juror can score. Network-driven, so wholly wrapped:
    a data-source outage must never break demo login.
    """
    from app.db.models import Holding, TradeTarget
    from app.routers.crypto import upsert_target_from_plan
    from app.settings import settings
    from app.tools.crypto_short_term import analyze_short_term

    try:
        has_targets = db.execute(
            select(TradeTarget.id).where(TradeTarget.user_id == user_id).limit(1)
        ).first()
        if has_targets:
            return  # already seeded — don't re-scan on every login

        existing_tickers = {
            t for (t,) in db.execute(
                select(Holding.ticker).where(Holding.user_id == user_id)
            ).all()
        }
        for sym in settings.crypto_basket:
            result = analyze_short_term(sym)
            target = upsert_target_from_plan(db, user_id, result)
            ticker = f"{sym}-USD"
            entry = (result.get("data") or {}).get("entry")
            if entry and ticker not in existing_tickers:
                db.add(Holding(
                    user_id=user_id,
                    ticker=ticker,
                    asset_class="crypto",
                    quantity=round(1500.0 / entry, 6),
                    cost_basis=entry,
                    currency="USD",
                ))
                existing_tickers.add(ticker)
            _ = target
        db.commit()
    except Exception:  # noqa: BLE001 — seeding is best-effort, never block login
        db.rollback()
        log.warning("demo crypto-basket seeding failed", exc_info=True)


@router.post("/demo", response_model=AuthResponse)
def demo_login(_rl: None = Depends(rate_limit("demo", limit=30))):
    """Return (or create) the demo user for hackathon jurors.

    Idempotent — safe to call many times. Seeds realistic data on first call.
    """
    DEMO_USERNAME = "demo"  # noqa: N806
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.username == DEMO_USERNAME)).scalar_one_or_none()
        if user is None:
            today = date.today()
            user = User(
                username=DEMO_USERNAME,
                password_hash=None,
                name="Demo Kullanıcı",
                avatar="fox",
                monthly_income=35000.0,
                risk_score=72,
                risk_profile="balanced",
                tier="pro",  # jurors/demo never hit the free monthly cap
            )
            db.add(user)
            db.flush()

            # Account
            acc = Account(user_id=user.id, name="Vadesiz Hesap", kind="checking", balance=1200.0, currency="TRY", institution="Demo Bank", color="emerald")
            db.add(acc)
            db.flush()

            # Transactions — current month + last month
            def tx(d: date, kind: str, amount: float, cat: str, desc: str):
                return Transaction(user_id=user.id, occurred_on=d, type=kind, amount=amount, currency="TRY", category=cat, description=desc, source="manual", account_id=acc.id)

            m0 = today.replace(day=1)  # first of this month
            m1 = (m0 - timedelta(days=1)).replace(day=1)  # first of last month
            db.add_all([
                # This month
                tx(m0, "income", 35000, "maaş", "Maaş"),
                tx(m0 + timedelta(days=2), "expense", 4200, "kira", "Kira"),
                tx(m0 + timedelta(days=3), "expense", 850, "market", "Migros"),
                tx(m0 + timedelta(days=4), "expense", 620, "market", "CarrefourSA"),
                tx(m0 + timedelta(days=5), "expense", 280, "faturalar", "Elektrik faturası"),
                tx(m0 + timedelta(days=5), "expense", 140, "faturalar", "Su faturası"),
                tx(m0 + timedelta(days=6), "expense", 195, "ulaşım", "İstanbulkart"),
                tx(m0 + timedelta(days=7), "expense", 320, "yemek", "Restoran"),
                tx(m0 + timedelta(days=8), "expense", 89, "eğlence", "Netflix"),
                tx(m0 + timedelta(days=9), "expense", 54, "eğlence", "Spotify"),
                tx(m0 + timedelta(days=10), "expense", 450, "giyim", "Zara"),
                tx(m0 + timedelta(days=12), "expense", 150, "sağlık", "Eczane"),
                tx(m0 + timedelta(days=14), "expense", 380, "yemek", "Yemeksepeti"),
                # Last month
                tx(m1, "income", 35000, "maaş", "Maaş"),
                tx(m1 + timedelta(days=2), "expense", 4200, "kira", "Kira"),
                tx(m1 + timedelta(days=3), "expense", 920, "market", "Migros"),
                tx(m1 + timedelta(days=5), "expense", 260, "faturalar", "Elektrik faturası"),
                tx(m1 + timedelta(days=6), "expense", 210, "ulaşım", "İstanbulkart"),
                tx(m1 + timedelta(days=8), "expense", 480, "yemek", "Restoran"),
                tx(m1 + timedelta(days=10), "expense", 89, "eğlence", "Netflix"),
                tx(m1 + timedelta(days=12), "expense", 680, "giyim", "Beymen"),
                tx(m1 + timedelta(days=15), "expense", 1200, "elektronik", "Teknosa"),
            ])

            # Goals
            db.add(Goal(user_id=user.id, title="Acil Durum Fonu", target_amount=50000, current_amount=1200, target_date=today + timedelta(days=365), icon="shield", currency="TRY"))
            db.add(Goal(user_id=user.id, title="Tatil Fonu", target_amount=20000, current_amount=3500, target_date=today + timedelta(days=180), icon="plane", currency="TRY"))

            # Holdings
            db.add(Holding(user_id=user.id, ticker="AAPL", asset_class="stock", quantity=5, cost_basis=170.0, currency="USD"))
            db.add(Holding(user_id=user.id, ticker="THYAO.IS", asset_class="stock", quantity=100, cost_basis=220.0, currency="TRY"))

            # Subscriptions
            db.add(Subscription(user_id=user.id, name="Netflix", amount=89, currency="TRY", cycle="monthly", direction="expense", next_charge_on=today + timedelta(days=20), category="eğlence", icon="tv"))
            db.add(Subscription(user_id=user.id, name="Spotify", amount=54, currency="TRY", cycle="monthly", direction="expense", next_charge_on=today + timedelta(days=22), category="eğlence", icon="music"))

            db.commit()
            db.refresh(user)

        # Idempotent crypto-basket + 4h-target seeding (every login; skipped once
        # seeded). Best-effort so a data-source outage never blocks demo access.
        _seed_crypto_basket(db, user.id)

        token = create_token(user.id, user.username)
        return AuthResponse(token=token, user=_user_dict(user))


@router.post("/firebase")
def firebase_signin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
):
    """Verify a Firebase ID token, create or fetch the local user, return profile."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")

    token = credentials.credentials

    # Verify Firebase token via firebase_verify (ensures _init() is called first)
    decoded = decode_firebase_token(token)
    if decoded is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid firebase token")

    firebase_uid: str = decoded["uid"]
    email: str = decoded.get("email", "")
    display_name: str = decoded.get("name", "")

    with SessionLocal() as db:
        user = db.execute(
            select(User).where(User.firebase_uid == firebase_uid)
        ).scalar_one_or_none()

        if user is None:
            # Derive a unique username from the email prefix
            base = email.split("@")[0] if email else firebase_uid[:16]
            base = re.sub(r"[^a-zA-Z0-9_.-]", "_", base)[:32]
            username, suffix = base, 1
            while db.execute(select(User).where(User.username == username)).scalar_one_or_none():
                username = f"{base[:29]}{suffix}"
                suffix += 1

            user = User(
                username=username,
                firebase_uid=firebase_uid,
                password_hash=None,
                name=display_name,
            )
            db.add(user)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                # Another request created the user concurrently — fetch it
                user = db.execute(
                    select(User).where(User.firebase_uid == firebase_uid)
                ).scalar_one()
            db.refresh(user)

        db.expunge(user)

    return _user_dict(user)
