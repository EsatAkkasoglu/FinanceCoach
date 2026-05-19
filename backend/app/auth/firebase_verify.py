"""Firebase ID token verification via firebase-admin SDK."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_initialized = False


def _init() -> bool:
    global _initialized
    if _initialized:
        return True
    try:
        import firebase_admin
        from firebase_admin import credentials

        if not firebase_admin._apps:
            import os
            cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
            project_id = os.environ.get("FIREBASE_PROJECT_ID", "fincoach-esat")
            if cred_path:
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred, {"projectId": project_id})
            else:
                # Application Default Credentials — works on Cloud Run automatically
                firebase_admin.initialize_app(options={"projectId": project_id})
        _initialized = True
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("firebase-admin init failed: %s", exc)
        return False


def verify_firebase_token(token: str) -> str | None:
    """Return the Firebase UID if the token is valid, else None."""
    if not _init():
        return None
    try:
        from firebase_admin import auth
        decoded = auth.verify_id_token(token)
        return str(decoded["uid"])
    except Exception:  # noqa: BLE001
        return None
