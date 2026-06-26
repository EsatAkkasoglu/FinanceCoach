"""KVKK / GDPR "right to erasure" — delete a user and all their data.

A user who asks to be forgotten must have *every* trace removed, not just the
``user`` row. This walks all user-scoped stores:

  • structured rows (holdings, transactions, goals, accounts, documents, chat,
    feedback, watchlist, alerts, usage, net-worth snapshots),
  • ChromaDB vectors (uploaded-document chunks + the per-user memory collection),
  • the LangGraph checkpointer transcript (best-effort; keyed by ``u{id}:`` thread).

Best-effort by design: a failure purging one vector store must not leave the
structured data half-deleted, so Chroma/checkpointer steps are guarded and the
relational delete is the source of truth. Returns a per-store summary so the
caller can log exactly what was removed.
"""
from __future__ import annotations

import logging

from sqlalchemy import delete, text

from app.db.models import (
    Account,
    BillingCheckout,
    ChatMessage,
    Conversation,
    Document,
    Goal,
    Holding,
    MessageFeedback,
    NetWorthSnapshot,
    NewsAlert,
    Subscription,
    Transaction,
    UsageCounter,
    User,
    Watchlist,
)

log = logging.getLogger("fincoach.account_deletion")

# FK-safe delete order: children that reference account/subscription/document
# (e.g. transaction) go before their parents; user goes last.
_USER_SCOPED_MODELS = [
    MessageFeedback,
    Transaction,       # → account / subscription / document
    Subscription,      # → account
    Document,
    NetWorthSnapshot,
    NewsAlert,
    Watchlist,
    UsageCounter,
    BillingCheckout,
    ChatMessage,
    Conversation,
    Goal,
    Holding,
    Account,
]


def _purge_chroma(user_id: int) -> dict:
    """Drop the user's document chunks + memory collection. Never raises."""
    out: dict = {"document_chunks": "skipped", "memory": "skipped"}
    try:
        import chromadb

        from app.settings import settings

        client = chromadb.PersistentClient(path=settings.chroma_path)

        # Shared collection, filtered by user_id metadata.
        try:
            col = client.get_or_create_collection(
                name="document_chunks", metadata={"hnsw:space": "cosine"}
            )
            col.delete(where={"user_id": user_id})
            out["document_chunks"] = "deleted"
        except Exception as exc:  # noqa: BLE001
            log.warning("chroma document_chunks purge failed for user %s: %s", user_id, exc)
            out["document_chunks"] = "error"

        # Per-user memory collection — drop the whole thing.
        try:
            client.delete_collection(name=f"fincoach_memory_u{user_id}")
            out["memory"] = "deleted"
        except Exception:  # noqa: BLE001 — no such collection is fine
            out["memory"] = "absent"
    except Exception as exc:  # noqa: BLE001 — chroma unavailable entirely
        log.warning("chroma unavailable during deletion for user %s: %s", user_id, exc)
    return out


def _purge_checkpointer(db, user_id: int) -> str:
    """Best-effort purge of LangGraph checkpoint rows for this user's threads.

    Thread ids are namespaced ``u{user_id}:...`` (see main.chat). The checkpointer
    lives in the same database as the app on both backends (SQLite file, or the
    same Neon Postgres URL — see settings.checkpointer_url), so deleting by thread
    prefix through the app session reaches it either way. Guarded: if the tables
    don't exist yet (no chat ever happened) we roll back and move on — the
    relational + vector purge already removes the user's content.
    """
    prefix = f"u{user_id}:%"
    deleted = 0
    for table in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
        try:
            res = db.execute(
                text(f"DELETE FROM {table} WHERE thread_id LIKE :p"), {"p": prefix}
            )
            deleted += res.rowcount or 0
        except Exception:  # noqa: BLE001 — table absent / not SQLite
            db.rollback()
    return f"rows~{deleted}"


def delete_user_account(db, user_id: int) -> dict:
    """Erase a user and all their data. Returns a summary dict for logging."""
    summary: dict = {"user_id": user_id, "rows": {}}

    for model in _USER_SCOPED_MODELS:
        res = db.execute(delete(model).where(model.user_id == user_id))
        summary["rows"][model.__tablename__] = res.rowcount or 0

    res = db.execute(delete(User).where(User.id == user_id))
    summary["rows"]["user"] = res.rowcount or 0
    db.commit()

    # Vector stores + transcript after the relational commit (best-effort).
    summary["chroma"] = _purge_chroma(user_id)
    summary["checkpointer"] = _purge_checkpointer(db, user_id)
    db.commit()

    log.info("account deletion complete: %s", summary)
    return summary
