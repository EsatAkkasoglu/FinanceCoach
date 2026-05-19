"""Firebase ID token verification via firebase-admin SDK."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_initialized = False


def _init() -> bool:
    global _initialized
    if _initialized:
        return True
    try:
        import os

        import firebase_admin
        from firebase_admin import credentials

        if not firebase_admin._apps:
            cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
            project_id = os.environ.get("FIREBASE_PROJECT_ID", "fincoach-esat")
            if cred_path:
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred, {"projectId": project_id})
            else:
                # Application Default Credentials — provided automatically on Cloud Run
                firebase_admin.initialize_app(options={"projectId": project_id})
            logger.info("firebase-admin initialised (project=%s)", project_id)
        _initialized = True
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("firebase-admin init failed: %s", exc)
        return False


def decode_firebase_token(token: str) -> dict[str, Any] | None:
    """Verify a Firebase ID token and return the full decoded claims, or None."""
    if not _init():
        return None
    try:
        from firebase_admin import auth
        return auth.verify_id_token(token)
    except Exception as exc:  # noqa: BLE001
        logger.debug("firebase token verification failed: %s", exc)
        return None


def verify_firebase_token(token: str) -> str | None:
    """Return the Firebase UID if the token is valid, else None."""
    decoded = decode_firebase_token(token)
    return str(decoded["uid"]) if decoded else None
