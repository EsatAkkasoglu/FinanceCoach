"""KVKK/GDPR provable consent — record that a user accepted the legal terms.

We stamp ``User.consented_at`` + ``User.consent_version`` so consent is
provable (who, when, which policy). ``CURRENT_CONSENT_VERSION`` is tied to the
effective date of the legal texts in the frontend (``legalContent.ts``); bump
it whenever those texts change materially so the UI can ask for re-consent.
"""
from __future__ import annotations

from datetime import datetime

from app.db.models import User

# Matches the "Last updated / Son güncelleme" date of the legal documents.
# Bump on any material change to Terms / Privacy-KVKK so users re-consent.
CURRENT_CONSENT_VERSION = "2026-06-26"


def consent_state(user: User) -> dict:
    """Serialize a user's consent status for API responses."""
    return {
        "consented": user.consented_at is not None,
        "consent_version": user.consent_version,
        "consent_current": user.consent_version == CURRENT_CONSENT_VERSION,
    }


def record_consent(db, user_id: int, *, version: str = CURRENT_CONSENT_VERSION) -> dict:
    """Stamp consent for a user. Idempotent — re-recording refreshes the time.

    Returns the consent state, or ``{"consented": False}`` if the user is gone.
    """
    user = db.get(User, user_id)
    if user is None:
        return {"consented": False, "consent_version": None, "consent_current": False}
    user.consented_at = datetime.utcnow()
    user.consent_version = version
    db.commit()
    return consent_state(user)
