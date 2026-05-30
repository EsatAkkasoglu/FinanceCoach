"""FastAPI dependencies: extract + verify bearer token (Firebase or JWT fallback)."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.auth.context import current_user_id_var
from app.auth.firebase_verify import verify_firebase_token
from app.auth.security import decode_token
from app.db.models import User
from app.db.session import SessionLocal

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")

    token = credentials.credentials

    # ── Legacy/demo JWT (HS256, local secret) ──────────────────────────────
    # Try this first: it's an offline signature check, so demo tokens never hit
    # the slow Firebase cert-fetch network call below. Real Firebase ID tokens
    # are RS256 and fail this decode, falling through to verification.
    try:
        payload = decode_token(token)
        user_id = int(payload["sub"])
    except Exception:  # noqa: BLE001
        user_id = None

    if user_id is not None:
        with SessionLocal() as db:
            user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
            if user is None:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
            db.expunge(user)
        current_user_id_var.set(user.id)
        return user

    # ── Firebase ID token ──────────────────────────────────────────────────
    firebase_uid = verify_firebase_token(token)
    if firebase_uid:
        with SessionLocal() as db:
            user = db.execute(
                select(User).where(User.firebase_uid == firebase_uid)
            ).scalar_one_or_none()
            if user is None:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "firebase user not synced")
            db.expunge(user)
        current_user_id_var.set(user.id)
        return user

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")


def get_current_user_id(user: User = Depends(get_current_user)) -> int:
    return user.id
