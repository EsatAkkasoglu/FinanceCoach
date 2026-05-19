"""/auth/register, /auth/login, /auth/me, /auth/firebase."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.deps import get_current_user
from app.auth.firebase_verify import verify_firebase_token
from app.auth.security import create_token, hash_password, verify_password
from app.db.models import User
from app.db.session import SessionLocal

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=128)


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
    }


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: Credentials):
    username = payload.username.strip().lower()
    if not USERNAME_RE.match(username):
        raise HTTPException(400, "username may only contain letters, digits, _ . -")

    with SessionLocal() as db:
        user = User(
            username=username,
            password_hash=hash_password(payload.password),
            name="",
        )
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
def login(payload: Credentials):
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


@router.post("/firebase")
def firebase_signin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
):
    """Verify a Firebase ID token, create or fetch the local user, return profile."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")

    token = credentials.credentials

    # Verify Firebase token and extract claims
    try:
        from firebase_admin import auth as fb_auth
        decoded = fb_auth.verify_id_token(token)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid firebase token") from exc

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
