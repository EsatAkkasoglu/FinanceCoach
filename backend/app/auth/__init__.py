"""Auth: bcrypt password hashing + JWT bearer tokens + FastAPI dependency.

Single shared SQLite DB; all per-user data is filtered by user_id. The current
user is resolved per-request from the `Authorization: Bearer <jwt>` header and
also exposed via a ContextVar so deeply-nested LangGraph tools can read it
without changing their signatures.
"""
from app.auth.context import (
    current_user_id_var,
    display_currency_var,
    get_current_user_id_or_none,
    get_display_currency,
    get_ui_language,
    ui_language_var,
)
from app.auth.deps import get_current_user, get_current_user_id
from app.auth.security import create_token, decode_token, hash_password, verify_password

__all__ = [
    "current_user_id_var",
    "display_currency_var",
    "ui_language_var",
    "get_ui_language",
    "get_current_user_id_or_none",
    "get_display_currency",
    "get_current_user",
    "get_current_user_id",
    "create_token",
    "decode_token",
    "hash_password",
    "verify_password",
]
