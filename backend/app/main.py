"""FastAPI sidecar entrypoint. Spawned by Tauri on app launch.

Endpoints:
    GET  /health              — liveness probe (used by Tauri to wait for ready)
    POST /chat                 — SSE-streamed multi-agent chat response
    GET  /portfolio            — list holdings
    POST /portfolio/holdings   — add holding
    POST /documents/upload     — multimodal PDF / image parse
    GET  /briefing             — daily personalized brief
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date as date_cls
from datetime import datetime
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.agents.supervisor import (
    ADVISOR_NODE,
    AGENT_NODES,
    STRATEGIST_NODE,
    SYNTHESIZER_NODE,
    build_supervisor,
)
from app.auth import current_user_id_var, get_current_user_id
from app.auth.routes import router as auth_router
from app.db.models import Conversation, Goal, Holding, MessageFeedback, User
from app.db.session import SessionLocal, init_db
from app.routers.admin import router as admin_router
from app.routers.audio import router as audio_router
from app.routers.billing import router as billing_router
from app.routers.budget import router as budget_router
from app.routers.crypto import router as crypto_router
from app.routers.funds import router as funds_router
from app.routers.fx import router as fx_router
from app.routers.insights import router as insights_router
from app.routers.memory import router as memory_router
from app.routers.networth import router as networth_router
from app.routers.news import router as news_router
from app.routers.symbols import router as symbols_router
from app.routers.waitlist import router as waitlist_router
from app.services.account_deletion import delete_user_account
from app.services.consent import record_consent
from app.services.document_processor.router import router as documents_router
from app.services.news_collector import shutdown_news_scheduler, start_news_scheduler
from app.services.usage import check_and_increment, get_usage
from app.settings import DEFAULT_JWT_SECRET, configure_langsmith, settings
from app.tools._cache import cache_reset

log = logging.getLogger("fincoach")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

_GOOGLE_API_KEY_RE = re.compile(r"AIza[0-9A-Za-z_-]{20,}")

# Secondary redaction sweep so a provider SDK that echoes a credential in its
# exception message can't leak it to the client. Each entry is (pattern, label).
# Conservative, high-signal shapes only — no generic "any long token" rule that
# would scrub harmless ids.
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"AIza[0-9A-Za-z_-]{20,}"), "GOOGLE_API_KEY"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "API_KEY"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}", re.IGNORECASE), "Bearer [REDACTED_TOKEN]"),
    (re.compile(r"\beyJ[A-Za-z0-9._-]{20,}"), "JWT"),  # JWT/Firebase ID tokens
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
                re.DOTALL), "PRIVATE_KEY"),
]

# Scrub Alpha Vantage rate-limit / premium-upsell notices out of tool output
# before it reaches the UI (used by _summarize_tool_output for non-JSON output).
_AV_RATELIMIT_RE = re.compile(
    r"(AV info[^\"\\}]*|We have detected your API key[^\"\\}]*?premium endpoints\.?"
    r"|.*?\b25 requests per day\b[^\"\\}]*?premium endpoints\.?"
    r"|Thank you for using Alpha Vantage[^\"\\}]*?premium plans[^\"\\}]*?)",
    re.IGNORECASE,
)


def _safe_error_message(exc: Exception) -> str:
    """Return a client-safe error without leaking provider API keys / tokens."""
    message = str(exc)
    for pattern, label in _SECRET_PATTERNS:
        repl = label if label.startswith("Bearer") else f"[REDACTED_{label}]"
        message = pattern.sub(repl, message)
    if "CONSUMER_SUSPENDED" in message or "has been suspended" in message:
        return (
            "Gemini API key is suspended. Create or rotate to a restricted Gemini API key "
            "for generativelanguage.googleapis.com, update backend/.env, and restart the backend."
        )
    return message


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("FinCoach starting up (demo_mode=%s)", settings.demo_mode)
    # Fail fast on a public deploy that still ships the well-known dev JWT secret —
    # anyone who read the repo could otherwise forge HS256 tokens for any user.
    # Prefer Firebase ID tokens in cloud; the local JWT path is for the sidecar.
    if settings.is_cloud_run and settings.jwt_secret == DEFAULT_JWT_SECRET:
        raise RuntimeError(
            "FINCOACH_JWT_SECRET must be overridden on Cloud Run (the default is public). "
            "Set a strong secret, or rely on Firebase ID tokens."
        )
    configure_langsmith()
    init_db()
    # Background news poller (thread-based; no-op if disabled). Runs in both the
    # SQLite and Postgres branches below — start it once here before they yield.
    start_news_scheduler()

    import threading

    from app.tools.fund_tools import prewarm_universe

    if settings.using_postgres:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        # Neon (serverless Postgres) closes idle server-side connections after
        # ~5 min. Cloud Run min-instances=0 means the instance may restart with
        # stale pool connections, causing "the connection is closed" errors.
        # min_size=0: no persistent connections while idle.
        # max_idle=60: evict connections idle for >60 s before Neon closes them.
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool
        pool = AsyncConnectionPool(
            settings.checkpointer_url,
            min_size=0,
            max_size=5,
            max_idle=60.0,
            open=False,
            # Must match from_conn_string defaults: autocommit + no prepared
            # statements (Neon serverless doesn't support them across connections)
            # + dict_row so LangGraph checkpoint queries parse correctly.
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        )
        await pool.open()
        try:
            checkpointer = AsyncPostgresSaver(pool)
            await checkpointer.setup()
            app.state.supervisor = build_supervisor(checkpointer=checkpointer)
            log.info("Supervisor built with AsyncPostgresSaver (psycopg pool); port %d", settings.port)
            threading.Thread(target=prewarm_universe, daemon=True, name="tefas-prewarm").start()
            yield
        finally:
            await pool.close()
    else:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        async with AsyncSqliteSaver.from_conn_string(settings.db_path) as checkpointer:
            app.state.supervisor = build_supervisor(checkpointer=checkpointer)
            log.info("Supervisor built with AsyncSqliteSaver; port %d", settings.port)
            threading.Thread(target=prewarm_universe, daemon=True, name="tefas-prewarm").start()
            yield

    shutdown_news_scheduler()
    log.info("FinCoach shutting down")


app = FastAPI(title="FinCoach API", version="0.1.0", lifespan=lifespan)


# Firebase Hosting rewrites `/api/**` to this Cloud Run service and forwards
# the full path unchanged, so the backend sees `/api/health` etc. Strip the
# prefix at the ASGI layer so local dev (no prefix) and prod (with prefix)
# both route to the same handlers.
@app.middleware("http")
async def strip_api_prefix(request, call_next):
    scope = request.scope
    path: str = scope.get("path", "")
    if path.startswith("/api/"):
        scope["path"] = path[len("/api"):]
        raw_path = scope.get("raw_path")
        if isinstance(raw_path, bytes) and raw_path.startswith(b"/api/"):
            scope["raw_path"] = raw_path[len(b"/api"):]
    return await call_next(request)


# Security headers on every API response. This service returns JSON (and the
# occasional HTML error page), so a maximally-strict CSP is safe here and just
# hardens any HTML the API ever emits. The frontend SPA gets its own, looser CSP
# via firebase.json. HSTS is only meaningful over real HTTPS (Cloud Run), so it's
# gated to avoid pinning HTTPS on plain-HTTP local dev.
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    if settings.is_cloud_run:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


# Local Tauri WebView2 + dev need a wildcard, but the same code runs on the public
# Cloud Run service — there, lock CORS to the Firebase Hosting origins so a third
# party can't make authenticated cross-origin calls for a logged-in user. (Prod is
# same-origin via the /api Hosting rewrite, so this is defense-in-depth.)
_CLOUD_ORIGINS = [
    "https://fincoach-esat.web.app",
    "https://fincoach-esat.firebaseapp.com",
]
# Explicit allow_headers ensures CORS headers appear on error responses too.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CLOUD_ORIGINS if settings.is_cloud_run else ["*"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Type", "Authorization"],
    max_age=600,
)

app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(audio_router)
app.include_router(budget_router)
app.include_router(fx_router)
app.include_router(funds_router)
app.include_router(symbols_router)
app.include_router(insights_router)
app.include_router(crypto_router)
app.include_router(memory_router)
app.include_router(networth_router)
app.include_router(admin_router)
app.include_router(news_router)
app.include_router(waitlist_router)
app.include_router(billing_router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "0.1.0",
        "demo_mode": settings.demo_mode,
        "model": settings.gemini_model,
    }


# ── Conversation management ──────────────────────────────────────────────────

@app.post("/conversations")
async def create_conversation(payload: dict, user_id: int = Depends(get_current_user_id)):
    """Create a new conversation thread and return its metadata."""
    conv_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    title = (payload.get("title") or "").strip() or None
    now = datetime.utcnow()
    with SessionLocal() as db:
        conv = Conversation(
            id=conv_id,
            user_id=user_id,
            thread_id=thread_id,
            title=title,
            created_at=now,
            updated_at=now,
        )
        db.add(conv)
        db.commit()
    return {"id": conv_id, "thread_id": thread_id, "title": title, "created_at": now.isoformat()}


@app.get("/conversations")
async def list_conversations(user_id: int = Depends(get_current_user_id)):
    """Return all non-archived conversations for the user, newest first."""
    with SessionLocal() as db:
        rows = db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id, Conversation.archived == 0)
            .order_by(Conversation.updated_at.desc())
        ).scalars().all()
        return [
            {
                "id": c.id,
                "thread_id": c.thread_id,
                "title": c.title,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
            }
            for c in rows
        ]


@app.patch("/conversations/{conv_id}")
async def update_conversation(
    conv_id: str, payload: dict, user_id: int = Depends(get_current_user_id)
):
    """Update conversation title."""
    with SessionLocal() as db:
        conv = db.execute(
            select(Conversation).where(Conversation.id == conv_id, Conversation.user_id == user_id)
        ).scalar_one_or_none()
        if conv is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        if "title" in payload:
            conv.title = payload["title"]
        db.commit()
    return {"ok": True}


# ── Message feedback (thumbs up / down) ──────────────────────────────────────

class FeedbackIn(BaseModel):
    thread_id: str = Field(min_length=1, max_length=64)
    message_id: str = Field(min_length=1, max_length=64)
    rating: Literal["up", "down"]
    reason: str | None = None
    agent: str | None = None
    excerpt: str | None = None


@app.post("/feedback")
async def post_feedback(payload: FeedbackIn, user_id: int = Depends(get_current_user_id)):
    """Upsert a thumbs-up / thumbs-down rating on a specific assistant message.

    Re-rating the same ``message_id`` overwrites the prior row (last write
    wins) rather than stacking. Best-effort: callers should treat 200 OK and
    silent failure equally — this never gates the chat UI.
    """
    excerpt = (payload.excerpt or "").strip()
    if len(excerpt) > 400:
        excerpt = excerpt[:400]
    reason = (payload.reason or "").strip() or None

    with SessionLocal() as db:
        row = db.execute(
            select(MessageFeedback).where(
                MessageFeedback.user_id == user_id,
                MessageFeedback.thread_id == payload.thread_id,
                MessageFeedback.message_id == payload.message_id,
            )
        ).scalar_one_or_none()
        if row is None:
            row = MessageFeedback(
                user_id=user_id,
                thread_id=payload.thread_id,
                message_id=payload.message_id,
                rating=payload.rating,
                reason=reason,
                agent=payload.agent,
                excerpt=excerpt or None,
            )
            db.add(row)
        else:
            row.rating = payload.rating
            row.reason = reason
            if payload.agent:
                row.agent = payload.agent
            if excerpt:
                row.excerpt = excerpt
        db.commit()
    return {"ok": True, "rating": payload.rating}


@app.post("/conversations/{conv_id}/autotitle")
async def autotitle_conversation(
    conv_id: str, payload: dict, user_id: int = Depends(get_current_user_id)
):
    """Generate a short (4-6 word) title from the user's first message via Gemini."""
    message: str = (payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message required")
    with SessionLocal() as db:
        conv = db.execute(
            select(Conversation).where(Conversation.id == conv_id, Conversation.user_id == user_id)
        ).scalar_one_or_none()
        if conv is None:
            raise HTTPException(status_code=404, detail="conversation not found")

    title = message[:60]
    try:
        from app.agents.llm import get_llm
        prompt = (
            "Generate a concise 4-6 word title for a finance chat that starts with "
            "the message below. Match the user's language (English or Turkish). "
            "Return ONLY the title — no quotes, no punctuation at the end, no prefix.\n\n"
            f"Message: {message[:500]}"
        )
        resp = await get_llm().ainvoke(prompt)
        raw = getattr(resp, "content", "")
        if isinstance(raw, list):
            raw = " ".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in raw)
        candidate = str(raw).strip().strip('"\'').strip()
        candidate = candidate.splitlines()[0] if candidate else ""
        if candidate:
            title = candidate[:80]
    except Exception as exc:
        log.warning("autotitle fallback (%s): %s", conv_id, _safe_error_message(exc))

    with SessionLocal() as db:
        conv = db.execute(
            select(Conversation).where(Conversation.id == conv_id, Conversation.user_id == user_id)
        ).scalar_one_or_none()
        if conv is not None:
            conv.title = title
            db.commit()
    return {"ok": True, "title": title}


@app.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str, user_id: int = Depends(get_current_user_id)):
    """Archive (soft-delete) a conversation."""
    with SessionLocal() as db:
        conv = db.execute(
            select(Conversation).where(Conversation.id == conv_id, Conversation.user_id == user_id)
        ).scalar_one_or_none()
        if conv is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        conv.archived = 1
        db.commit()
    return {"ok": True}


# ── Usage / plan limits ──────────────────────────────────────────────────────

@app.get("/usage")
async def read_usage(user_id: int = Depends(get_current_user_id)):
    """Current month's metered usage for the authenticated user (UI meter)."""
    with SessionLocal() as db:
        tier = db.execute(select(User.tier).where(User.id == user_id)).scalar_one_or_none()
        return get_usage(db, user_id, tier)


# ── Account / KVKK data rights ────────────────────────────────────────────────

@app.post("/account/consent", status_code=200)
async def post_consent(user_id: int = Depends(get_current_user_id)):
    """Record KVKK/Terms consent for the signed-in user (current policy version).

    Used by sign-up paths that can't stamp consent inline (e.g. Google/Firebase)
    and to re-consent after a policy update. Idempotent.
    """
    with SessionLocal() as db:
        return record_consent(db, user_id)


@app.delete("/account", status_code=200)
async def delete_account(user_id: int = Depends(get_current_user_id)):
    """KVKK/GDPR right to erasure: delete the user and all their data.

    Irreversible. Purges every user-scoped store (relational rows, ChromaDB
    document + memory vectors, chat-transcript checkpoints). The client must
    drop its session afterwards (the bearer token now points at a gone user).
    """
    with SessionLocal() as db:
        summary = delete_user_account(db, user_id)
    return {"ok": True, "deleted": summary["rows"]}


# ── Chat ─────────────────────────────────────────────────────────────────────

@app.post("/chat")
async def chat(payload: dict, user_id: int = Depends(get_current_user_id)):
    """Stream multi-agent response as SSE events.

    Requires `thread_id` in payload — each conversation has its own thread_id.
    The checkpointer automatically loads & persists full message history per thread.

    Event flow (astream_events v2):
        agent_start(supervisor)
        → on_chain_end(supervisor)  → agent_done(supervisor) + agent_start(worker)
        → on_tool_start(*)          → tool_call (real-time, per tool invocation)
        → on_chain_end(worker)      → citations + token* + agent_done(worker)
        → done
    """
    user_message: str = payload.get("message", "").strip()
    thread_id: str = payload.get("thread_id", "").strip()
    conv_id: str = payload.get("conv_id", "").strip()
    display_currency: str = (payload.get("display_currency") or "USD").strip().upper()
    if display_currency not in {"TRY", "USD", "EUR"}:
        display_currency = "USD"
    ui_language: str = (payload.get("language") or "en").strip().lower()[:2]
    if ui_language not in {"en", "tr"}:
        ui_language = "en"
    if not user_message:
        return {"error": "empty message"}
    if not thread_id:
        return {"error": "thread_id required"}

    # Enforce that the conversation/thread belongs to this user before we let
    # them write into the checkpointer keyed off thread_id.
    if conv_id:
        with SessionLocal() as db:
            owns = db.execute(
                select(Conversation.thread_id).where(
                    Conversation.id == conv_id, Conversation.user_id == user_id
                )
            ).scalar_one_or_none()
            if owns is None or owns != thread_id:
                raise HTTPException(403, "conversation not found")

    # Plan gate: count this metered (LLM-spending) turn and refuse free-tier
    # users who've hit the monthly cap — before we start any Gemini work.
    with SessionLocal() as db:
        tier = db.execute(select(User.tier).where(User.id == user_id)).scalar_one_or_none()
        allowed, usage = check_and_increment(db, user_id, tier)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "monthly_limit_reached",
                "message": "Aylık mesaj limitine ulaştın. Pro'ya geçince sınırsız.",
                "usage": usage,
            },
        )

    # Make user_id + UI display currency visible to deeply-nested LangGraph
    # tools / synthesizer via ContextVars.
    current_user_id_var.set(user_id)
    from app.auth import display_currency_var, ui_language_var
    display_currency_var.set(display_currency)
    ui_language_var.set(ui_language)

    supervisor = app.state.supervisor
    initial_state = {"messages": [HumanMessage(content=user_message)], "user_id": user_id}
    # Namespace thread_id by user so checkpoint keys can never collide across users.
    config = {"configurable": {"thread_id": f"u{user_id}:{thread_id}"}}

    def _evt(event: str, data: dict) -> dict:
        return {"event": event, "data": json.dumps(data)}

    def _safe_args(args: object) -> dict:
        """Coerce tool args to a plain JSON-safe dict (guard against large/circular)."""
        if isinstance(args, dict):
            try:
                json.dumps(args)
                return args
            except (TypeError, ValueError):
                pass
        return {"raw": str(args)[:200]}

    final_chunks: list[str] = []
    final_agent: str | None = None

    async def event_stream():
        nonlocal final_agent
        # Re-bind in case the generator runs in a fresh asyncio task that
        # didn't inherit the request handler's ContextVar value.
        current_user_id_var.set(user_id)
        # Fresh per-turn tool cache so parallel specialists share quote lookups
        # but state never leaks across turns.
        cache_reset()

        # Top-level node names we surface as activity to the frontend. Every
        # one runs inside the graph; only the synthesizer ends up in a visible
        # bubble — everything else is `internal: True` (activity panel only).
        INTERNAL_NODES = {STRATEGIST_NODE, ADVISOR_NODE, *AGENT_NODES.keys()}  # noqa: N806

        # Track which top-level node a tool call is happening under so the
        # UI can attribute each tool chip to its desk. With parallel specialist
        # execution we approximate by looking at `metadata.langgraph_node`.
        done_nodes: set[str] = set()
        started_nodes: set[str] = set()
        collected_citations: list[dict] = []
        # XAI: capture structured reasoning emitted by advisor / risk_profiler
        # so we can ship it to the UI alongside the final reply.
        advisor_brief_seen: dict | None = None
        risk_brief_seen: dict | None = None

        try:
            async for ev in supervisor.astream_events(initial_state, config=config, version="v2"):
                kind: str = ev["event"]
                name: str = ev.get("name", "")
                node: str = ev.get("metadata", {}).get("langgraph_node", "")
                data: dict = ev.get("data", {})

                # ── Top-level node started ───────────────────────────────
                if kind == "on_chain_start" and name in INTERNAL_NODES and name not in started_nodes:
                    started_nodes.add(name)
                    yield _evt("agent_start", {"agent": name, "internal": True})

                elif kind == "on_chain_start" and name == SYNTHESIZER_NODE and name not in started_nodes:
                    started_nodes.add(name)
                    yield _evt("agent_start", {"agent": SYNTHESIZER_NODE, "internal": False})
                    final_agent = SYNTHESIZER_NODE

                # ── Real-time tool call inside a specialist's ReAct loop ─
                elif kind == "on_tool_start" and node == "tools":
                    tool_input = data.get("input") or {}
                    # `metadata.langgraph_node` is the parent specialist name
                    # when we're inside its ReAct sub-graph (e.g. "market_data").
                    parent_meta = ev.get("metadata", {}).get("langgraph_checkpoint_ns", "")
                    parent_agent = ""
                    for known in AGENT_NODES:
                        if known in parent_meta:
                            parent_agent = known
                            break
                    yield _evt("tool_call", {
                        "tool": name,
                        "args": _safe_args(tool_input),
                        "agent": parent_agent,
                        "run_id": ev.get("run_id", ""),
                    })

                elif kind == "on_tool_end" and node == "tools":
                    raw_output = data.get("output")
                    result_text = _summarize_tool_output(raw_output)
                    yield _evt("tool_result", {
                        "tool": name,
                        "result": result_text,
                        "run_id": ev.get("run_id", ""),
                    })

                # ── Specialist finished → collect citations ──────────────
                elif kind == "on_chain_end" and name in AGENT_NODES and name not in done_nodes:
                    done_nodes.add(name)
                    output = data.get("output") or {}
                    if isinstance(output, dict):
                        err = output.get("error")
                        citations = output.get("citations") or []
                        if citations:
                            collected_citations.extend(
                                {**c, "agent": name} for c in citations
                            )
                        # Capture risk_profiler's structured brief for XAI.
                        if name == "risk_profiler":
                            findings = output.get("findings") or {}
                            rp = findings.get("risk_profiler") if isinstance(findings, dict) else None
                            if isinstance(rp, dict):
                                extra = rp.get("extra") or {}
                                if isinstance(extra, dict) and isinstance(extra.get("brief"), dict):
                                    risk_brief_seen = extra["brief"]
                        if err:
                            log.warning(
                                "specialist %s errored (folded into advisor/synthesizer): %s/%s",
                                name, err.get("type"), err.get("message"),
                            )
                    yield _evt("agent_done", {"agent": name})

                # ── Strategist / advisor finished — internal, silent end ─
                elif kind == "on_chain_end" and name in {STRATEGIST_NODE, ADVISOR_NODE} and name not in done_nodes:
                    done_nodes.add(name)
                    if name == ADVISOR_NODE:
                        output = data.get("output") or {}
                        if isinstance(output, dict):
                            brief = output.get("advisor_brief")
                            if isinstance(brief, dict):
                                advisor_brief_seen = brief
                    yield _evt("agent_done", {"agent": name})

                # ── Synthesizer finished → emit the single visible reply ─
                elif kind == "on_chain_end" and name == SYNTHESIZER_NODE and name not in done_nodes:
                    done_nodes.add(name)
                    output = data.get("output") or {}

                    if isinstance(output, dict):
                        err = output.get("error")
                        msgs = output.get("messages") or []
                        content = ""
                        if msgs:
                            content = _normalize_content(getattr(msgs[-1], "content", ""))

                        if err:
                            yield _evt("agent_error", {
                                "agent": name,
                                "type": str(err.get("type", "AgentError")),
                                "message": _safe_error_message(Exception(str(err.get("message", "")))),
                            })
                        elif content:
                            final_chunks.append(content)
                            yield _evt("agent_message", {"agent": name})
                            if collected_citations:
                                yield _evt("citations", {
                                    "agent": name,
                                    "items": collected_citations,
                                })
                            # XAI: surface structured "why this recommendation"
                            # data so the UI can render a reasoning panel.
                            if advisor_brief_seen and (
                                advisor_brief_seen.get("why_summary")
                                or advisor_brief_seen.get("key_drivers")
                            ):
                                yield _evt("agent_reasoning", {
                                    "agent": "advisor",
                                    "why_summary": advisor_brief_seen.get("why_summary", ""),
                                    "key_drivers": advisor_brief_seen.get("key_drivers", []),
                                    "allocation_drivers": [
                                        {
                                            "asset_class": b.get("asset_class", ""),
                                            "drivers": b.get("drivers", []),
                                        }
                                        for b in (advisor_brief_seen.get("allocation") or [])
                                        if isinstance(b, dict)
                                    ],
                                })
                            if risk_brief_seen and (
                                risk_brief_seen.get("reasoning")
                                or risk_brief_seen.get("drivers")
                            ):
                                yield _evt("agent_reasoning", {
                                    "agent": "risk_profiler",
                                    "why_summary": " ".join(
                                        risk_brief_seen.get("reasoning") or []
                                    ).strip(),
                                    "key_drivers": risk_brief_seen.get("drivers", []),
                                    "risk_score": risk_brief_seen.get("score"),
                                    "profile": risk_brief_seen.get("profile"),
                                    "equity_band": [
                                        risk_brief_seen.get("equity_low"),
                                        risk_brief_seen.get("equity_high"),
                                    ],
                                })
                            for tok in _chunked(content, 24):
                                yield _evt("token", {"text": tok})
                            suggestions = output.get("suggestions") or []
                            if isinstance(suggestions, list) and suggestions:
                                yield _evt("suggestions", {
                                    "agent": name,
                                    "items": [str(s)[:200] for s in suggestions[:4]],
                                })
                        else:
                            log.warning("synthesizer ended with no content")
                            yield _evt("agent_error", {
                                "agent": name,
                                "type": "empty_response",
                                "message": "Synthesizer produced no text. Check server logs.",
                            })

                    yield _evt("agent_done", {"agent": name})

        except Exception as exc:  # noqa: BLE001
            log.exception("chat stream failed")
            yield _evt("error", {"message": _safe_error_message(exc)})
        finally:
            full_response = "\n\n".join(final_chunks).strip()
            if full_response:
                from app.tools.memory_tools import upsert_chat_turn
                upsert_chat_turn(user_message, full_response, final_agent)
            # Update conversation updated_at + auto-title on first message
            if conv_id:
                _touch_conversation(conv_id, user_id, user_message)
            yield _evt("done", {})

    # ping=20: sse_starlette sends a ": ping" comment every 20 s to keep
    # Cloud Run's load balancer from closing idle SSE connections (~60 s timeout).
    return EventSourceResponse(event_stream(), ping=20)


def _touch_conversation(conv_id: str, user_id: int, first_message: str) -> None:
    """Update updated_at and auto-generate title from first message if missing.

    Scoped to the owning user so the row can only ever be touched by its owner
    (defense-in-depth — the only caller already authenticates the user).
    """
    with SessionLocal() as db:
        conv = db.execute(
            select(Conversation).where(
                Conversation.id == conv_id, Conversation.user_id == user_id
            )
        ).scalar_one_or_none()
        if conv is None:
            return
        conv.updated_at = datetime.utcnow()
        if not conv.title:
            conv.title = first_message[:60].strip()
        db.commit()


# Keys whose values are diagnostic-only (raw provider error text) and should
# NEVER reach the UI. They stay in backend logs but are stripped from any
# tool output that gets serialized into a citation chip.
_SCRUBBED_KEYS = {"cg_error", "cg_trending_error"}


def _scrub_for_ui(obj: object) -> object:
    """Recursively drop diagnostic-only keys so they never appear in the
    citations panel. Logs whatever it strips so operators can see it.
    """
    if isinstance(obj, dict):
        cleaned: dict = {}
        for k, v in obj.items():
            if k in _SCRUBBED_KEYS:
                log.info("scrubbed tool-output key for UI: %s=%r", k, v)
                continue
            cleaned[k] = _scrub_for_ui(v)
        return cleaned
    if isinstance(obj, list):
        return [_scrub_for_ui(x) for x in obj]
    return obj


def _summarize_tool_output(output: object) -> str:
    """Return a short human-readable summary of a tool's return value.

    LangChain wraps tool returns in ToolMessage objects whose ``str()`` is
    ``content='...' name='...' tool_call_id='...'`` — useless for the UI.
    Unwrap to the inner ``.content`` (which is what the tool actually
    returned, already a JSON string for dict/list returns) before serializing.
    """
    if output is None:
        return "no result"
    # Unwrap ToolMessage / AIMessage-like objects to their content payload.
    inner = getattr(output, "content", None)
    if inner is not None:
        output = inner

    # Tools often return JSON strings; parse so we can scrub structurally,
    # then re-serialize. Fall back to plain-string scrub if not JSON.
    parsed: object | None = None
    if isinstance(output, str):
        try:
            parsed = json.loads(output)
        except (ValueError, TypeError):
            parsed = None
        if parsed is None:
            text = _AV_RATELIMIT_RE.sub("data provider rate-limited", output)
        else:
            text = json.dumps(_scrub_for_ui(parsed), ensure_ascii=False, default=str)
    else:
        text = json.dumps(_scrub_for_ui(output), ensure_ascii=False, default=str)
    text = text.strip()
    # Keep enough payload that the UI can pretty-print structured results.
    return text[:4000] + ("…" if len(text) > 4000 else "")


def _chunked(text: str, size: int):
    """Split the final agent message into small chunks for typewriter animation."""
    for i in range(0, len(text), size):
        yield text[i : i + size]


def _normalize_content(content) -> str:
    """Collapse LangChain message content to a plain string.

    Newer LangChain + Gemini 3.x return content as a list of structured parts
    (e.g. ``[{"type": "text", "text": "...", "extras": {...}}]``). We
    concatenate the text parts and ignore non-text (images, signatures).
    Older AIMessages still come through as bare strings.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict):
                if isinstance(p.get("text"), str):
                    parts.append(p["text"])
        return "".join(parts)
    return str(content) if content is not None else ""


# --- Onboarding -----------------------------------------------------------


class GoalIn(BaseModel):
    title: str
    target_amount: float
    target_date: str = ""
    icon: str = "target"


class HoldingIn(BaseModel):
    ticker: str
    quantity: float
    cost_basis: float = 0.0
    asset_class: Literal["stock", "crypto", "cash", "etf", "bond"] = "stock"


class OnboardingIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    avatar: str = "fox"
    monthly_income: float = 0.0
    risk_score: int = Field(ge=0, le=125)
    risk_profile: Literal["conservative", "balanced", "aggressive"]
    spending_pace: int = Field(ge=1, le=5, default=3)
    goal: GoalIn | None = None
    holdings: list[HoldingIn] = []


def _parse_date(value: str) -> date_cls | None:
    if not value:
        return None
    try:
        return date_cls.fromisoformat(value)
    except ValueError:
        return None


@app.post("/onboarding")
async def onboarding(payload: OnboardingIn, user_id: int = Depends(get_current_user_id)):
    """Persist the onboarding wizard output into the current user's profile."""
    _invalidate_portfolio_cache(user_id)
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if user is None:
            raise HTTPException(404, "user not found")

        user.name = payload.name
        user.avatar = payload.avatar
        user.monthly_income = payload.monthly_income
        user.risk_score = payload.risk_score
        user.risk_profile = payload.risk_profile

        if payload.goal is not None:
            db.add(
                Goal(
                    user_id=user.id,
                    title=payload.goal.title,
                    target_amount=payload.goal.target_amount,
                    target_date=_parse_date(payload.goal.target_date),
                    icon=payload.goal.icon,
                )
            )

        for h in payload.holdings:
            if not h.ticker.strip() or h.quantity <= 0:
                continue
            db.add(
                Holding(
                    user_id=user.id,
                    ticker=h.ticker.upper(),
                    quantity=h.quantity,
                    cost_basis=h.cost_basis,
                    asset_class=h.asset_class,
                )
            )

        try:
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            log.exception("onboarding commit failed")
            raise HTTPException(status_code=500, detail=_safe_error_message(exc)) from exc

        return {"ok": True, "user_id": user.id}


# --- Portfolio + Briefing -----------------------------------------------

# Per-user in-memory portfolio cache: user_id → (result_dict, timestamp)
_portfolio_cache: dict[int, tuple[dict, float]] = {}
_PORTFOLIO_TTL = 120  # seconds


def _invalidate_portfolio_cache(user_id: int) -> None:
    _portfolio_cache.pop(user_id, None)


def _quote_or_none(ticker: str, asset_class: str | None = None) -> dict | None:
    """Wrap get_quote tool with safe error handling (briefing must never 500).

    Routes TEFAS funds (asset_class='fund') through ``get_fund_quote`` since
    those codes aren't on yfinance and would otherwise log spurious
    "possibly delisted" errors.
    """
    try:
        if asset_class == "fund":
            from app.tools.fund_tools import get_fund_quote
            result = get_fund_quote.invoke({"code": ticker})
            # get_fund_quote returns {code, title, price, currency, …} on success
            # or {code, error} on failure — there is NO "ok" key. The old check
            # required result["ok"], so it ALWAYS fell through to None and the
            # portfolio showed cost basis as the live price (0 % gain for funds).
            if not isinstance(result, dict) or result.get("error") or not result.get("price"):
                return None
            return {"price": result["price"], "currency": result.get("currency", "TRY")}
        from app.tools.market_tools import get_quote
        result = get_quote.invoke({"ticker": ticker})
        if "error" in result:
            return None
        return result
    except Exception as exc:  # noqa: BLE001
        log.warning("quote fetch failed for %s: %s", ticker, exc)
        return None


@app.get("/portfolio")
async def list_portfolio(user_id: int = Depends(get_current_user_id)):
    """Return the user's holdings enriched with current price + P&L.

    Fetches all quotes in parallel via asyncio.gather + thread pool so N holdings
    cost ~1 round-trip instead of N sequential Alpha Vantage calls.
    Results are cached per-user for 2 minutes to avoid hammering yfinance on every
    page navigation.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    now = time.time()
    cached = _portfolio_cache.get(user_id)
    if cached and now - cached[1] < _PORTFOLIO_TTL:
        return cached[0]

    with SessionLocal() as db:
        rows = db.execute(select(Holding).where(Holding.user_id == user_id)).scalars().all()

    non_cash = [h for h in rows if h.asset_class != "cash"]

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=min(len(non_cash) or 1, 10)) as pool:
        quotes = await asyncio.gather(
            *[
                loop.run_in_executor(pool, _quote_or_none, h.ticker, h.asset_class)
                for h in non_cash
            ],
            return_exceptions=True,
        )
    quote_map = {
        h.ticker: (q if isinstance(q, dict) else None)
        for h, q in zip(non_cash, quotes, strict=False)
    }

    enriched: list[dict] = []
    total_value = 0.0
    total_cost = 0.0
    total_day_pnl = 0.0

    for h in rows:
        cost_total = h.quantity * h.cost_basis
        change_today = None
        day_pnl = None
        if h.asset_class == "cash":
            current_price = 1.0
            current_value = h.quantity
            currency = h.currency or "USD"
        else:
            quote = quote_map.get(h.ticker)
            current_price = quote["price"] if quote else h.cost_basis
            currency = (quote or {}).get("currency") or h.currency or "USD"
            current_value = h.quantity * current_price
            # Per-position day change. `get_quote` returns change_pct (1-day %).
            # Surface it so the dashboard hero / holdings rows can show today's move.
            if quote is not None and quote.get("change_pct") is not None:
                change_today = round(quote["change_pct"], 2)
                day_pnl = round(current_value * (change_today / 100.0), 2)
                total_day_pnl += day_pnl

        pnl = current_value - cost_total
        pnl_pct = (pnl / cost_total * 100.0) if cost_total else 0.0
        enriched.append({
            "id": h.id,
            "ticker": h.ticker,
            "asset_class": h.asset_class,
            "quantity": h.quantity,
            "cost_basis": h.cost_basis,
            "current_price": round(current_price, 4),
            "current_value": round(current_value, 2),
            "cost_total": round(cost_total, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "change_today": change_today,
            "day_pnl": day_pnl,
            "currency": currency,
        })
        total_value += current_value
        total_cost += cost_total

    day_pnl_pct = (total_day_pnl / total_value * 100.0) if total_value else 0.0
    result = {
        "holdings": enriched,
        "totals": {
            "value": round(total_value, 2),
            "cost": round(total_cost, 2),
            "pnl": round(total_value - total_cost, 2),
            "pnl_pct": round(((total_value - total_cost) / total_cost * 100.0) if total_cost else 0.0, 2),
            "day_pnl": round(total_day_pnl, 2),
            "day_pnl_pct": round(day_pnl_pct, 2),
            "count": len(enriched),
        },
    }
    _portfolio_cache[user_id] = (result, time.time())
    return result


class HoldingCreate(BaseModel):
    ticker: str = Field(min_length=1, max_length=32)
    quantity: float = Field(gt=0)
    cost_basis: float = Field(default=0.0, ge=0)
    asset_class: Literal["stock", "crypto", "cash", "etf", "bond", "fund"] = "stock"


class HoldingUpdate(BaseModel):
    ticker: str | None = Field(default=None, min_length=1, max_length=32)
    quantity: float | None = Field(default=None, gt=0)
    cost_basis: float | None = Field(default=None, ge=0)
    asset_class: Literal["stock", "crypto", "cash", "etf", "bond", "fund"] | None = None


@app.post("/portfolio/holdings")
async def add_holding(payload: HoldingCreate, user_id: int = Depends(get_current_user_id)):
    """Add a holding to the user's portfolio."""
    _invalidate_portfolio_cache(user_id)
    with SessionLocal() as db:
        h = Holding(
            user_id=user_id,
            ticker=payload.ticker.upper().strip(),
            asset_class=payload.asset_class,
            quantity=payload.quantity,
            cost_basis=payload.cost_basis,
        )
        db.add(h)
        db.commit()
        db.refresh(h)
        return {"ok": True, "id": h.id, "ticker": h.ticker}


@app.patch("/portfolio/holdings/{holding_id}")
async def update_holding(
    holding_id: int, payload: HoldingUpdate, user_id: int = Depends(get_current_user_id)
):
    """Patch a single holding. Only fields present in the body are touched."""
    _invalidate_portfolio_cache(user_id)
    with SessionLocal() as db:
        h = db.execute(
            select(Holding).where(Holding.id == holding_id, Holding.user_id == user_id)
        ).scalar_one_or_none()
        if h is None:
            raise HTTPException(status_code=404, detail="holding not found")
        if payload.ticker is not None:
            h.ticker = payload.ticker.upper().strip()
        if payload.quantity is not None:
            h.quantity = payload.quantity
        if payload.cost_basis is not None:
            h.cost_basis = payload.cost_basis
        if payload.asset_class is not None:
            h.asset_class = payload.asset_class
        db.commit()
        db.refresh(h)
        return {
            "ok": True,
            "id": h.id,
            "ticker": h.ticker,
            "quantity": h.quantity,
            "cost_basis": h.cost_basis,
            "asset_class": h.asset_class,
        }


@app.delete("/portfolio/holdings/{holding_id}")
async def delete_holding(holding_id: int, user_id: int = Depends(get_current_user_id)):
    """Remove a holding."""
    _invalidate_portfolio_cache(user_id)
    with SessionLocal() as db:
        h = db.execute(
            select(Holding).where(Holding.id == holding_id, Holding.user_id == user_id)
        ).scalar_one_or_none()
        if h is None:
            raise HTTPException(status_code=404, detail="holding not found")
        db.delete(h)
        db.commit()
    return {"ok": True}


# --- Profile -------------------------------------------------------------


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    avatar: str | None = Field(default=None, max_length=64)
    monthly_income: float | None = Field(default=None, ge=0)
    risk_score: int | None = Field(default=None, ge=0, le=125)
    risk_profile: Literal["conservative", "balanced", "aggressive"] | None = None
    roast_mode: bool | None = None


def _serialize_user(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "has_onboarded": bool(user.name),
        "name": user.name,
        "avatar": user.avatar,
        "monthly_income": user.monthly_income,
        "risk_score": user.risk_score,
        "risk_profile": user.risk_profile,
        "roast_mode": bool(user.roast_mode),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@app.get("/profile")
async def get_profile(user_id: int = Depends(get_current_user_id)):
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="profile not found")
        return _serialize_user(user)


@app.patch("/profile")
async def update_profile(payload: ProfileUpdate, user_id: int = Depends(get_current_user_id)):
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="profile not found")
        if payload.name is not None:
            user.name = payload.name
        if payload.avatar is not None:
            user.avatar = payload.avatar
        if payload.monthly_income is not None:
            user.monthly_income = payload.monthly_income
        if payload.risk_score is not None:
            user.risk_score = payload.risk_score
        if payload.risk_profile is not None:
            user.risk_profile = payload.risk_profile
        if payload.roast_mode is not None:
            user.roast_mode = 1 if payload.roast_mode else 0
        db.commit()
        db.refresh(user)
        return _serialize_user(user)


_BRIEFING_CACHE: dict[int, tuple[float, dict]] = {}
_BRIEFING_TTL_SECONDS = 15 * 60


def _trends_or_none() -> dict | None:
    try:
        from app.tools.market_tools import scan_hot_trends
        return scan_hot_trends.invoke({"no_social": False})
    except Exception as exc:  # noqa: BLE001
        log.warning("scan_hot_trends failed: %s", exc)
        return None


def _news_or_none(query: str) -> list[dict] | None:
    try:
        from app.tools.news_tools import search_news
        return search_news.invoke({"query": query, "limit": 3})
    except Exception as exc:  # noqa: BLE001
        log.warning("search_news failed: %s", exc)
        return None


def _dividend_or_none(ticker: str) -> dict | None:
    try:
        from app.tools.market_tools import get_dividend_metrics
        res = get_dividend_metrics.invoke({"ticker": ticker})
        if isinstance(res, dict) and not res.get("error"):
            return res
    except Exception as exc:  # noqa: BLE001
        log.warning("get_dividend_metrics failed for %s: %s", ticker, exc)
    return None


@app.get("/briefing")
async def daily_briefing(user_id: int = Depends(get_current_user_id)):
    """Personalized 5-7 item briefing for the dashboard widget.

    Combines (a) market context — S&P 500 + VIX, (b) personal — portfolio
    day move, (c) discovery — trending US movers, (d) news — fresh headline
    for one of the user's holdings, (e) income — dividend alert for the
    biggest div-paying holding. All external calls run in parallel and
    failures degrade silently. Results cached per-user for 15 minutes.
    """
    import asyncio
    import time
    from concurrent.futures import ThreadPoolExecutor

    cached = _BRIEFING_CACHE.get(user_id)
    if cached and time.time() - cached[0] < _BRIEFING_TTL_SECONDS:
        return cached[1]

    with SessionLocal() as db:
        holdings = db.execute(select(Holding).where(Holding.user_id == user_id)).scalars().all()

    non_cash = [h for h in holdings if h.asset_class != "cash"]
    # Pick "main" holding by quantity * cost_basis as a cheap proxy for size.
    main_holding = max(
        non_cash, key=lambda h: (h.quantity or 0) * (h.cost_basis or 0), default=None,
    )
    div_candidates = [h for h in non_cash if h.asset_class in ("stock", "etf")][:1]
    div_ticker = div_candidates[0].ticker if div_candidates else None

    # (ticker, asset_class) — indices flow through yfinance; fund holdings via TEFAS.
    quote_specs: list[tuple[str, str | None]] = [("^GSPC", None), ("^VIX", None)]
    quote_specs.extend((h.ticker, h.asset_class) for h in non_cash)
    tickers_to_fetch = [t for t, _ in quote_specs]
    aux_jobs: list = []  # (name, callable, *args)
    aux_jobs.append(("trends", _trends_or_none))
    if main_holding:
        aux_jobs.append(("news", _news_or_none, main_holding.ticker))
    if div_ticker:
        aux_jobs.append(("dividend", _dividend_or_none, div_ticker))

    loop = asyncio.get_event_loop()
    pool_size = min(len(tickers_to_fetch) + len(aux_jobs), 12)
    with ThreadPoolExecutor(max_workers=pool_size) as pool:
        quote_futs = [loop.run_in_executor(pool, _quote_or_none, t, ac) for t, ac in quote_specs]
        aux_futs = [loop.run_in_executor(pool, j[1], *j[2:]) for j in aux_jobs]
        results = await asyncio.gather(*quote_futs, *aux_futs, return_exceptions=True)

    def _safe(r):
        return r if isinstance(r, (dict, list)) else None

    spx = _safe(results[0])
    vix = _safe(results[1])
    holding_quotes = {h.ticker: _safe(results[2 + i]) for i, h in enumerate(non_cash)}
    aux_results = {j[0]: _safe(results[len(tickers_to_fetch) + i]) for i, j in enumerate(aux_jobs)}

    items: list[dict] = []

    # 1. Market — S&P 500
    if spx:
        sign = "+" if spx["change_pct"] >= 0 else ""
        items.append({
            "icon": "trending_up" if spx["change_pct"] >= 0 else "trending_down",
            "label": "Market",
            "text": f"S&P 500 {sign}{spx['change_pct']:.2f}% today (close {spx['price']:.2f})",
            "tone": "positive" if spx["change_pct"] >= 0 else "negative",
        })

    # 2. Personal — portfolio day move
    try:
        if holdings:
            day_pnl = 0.0
            base_value = 0.0
            for h in holdings:
                if h.asset_class == "cash":
                    base_value += h.quantity
                    continue
                quote = holding_quotes.get(h.ticker)
                if not quote:
                    continue
                price = quote["price"]
                day_change = price * (quote["change_pct"] / 100.0)
                day_pnl += h.quantity * day_change
                base_value += h.quantity * price
            if base_value:
                day_pct = (day_pnl / base_value * 100.0) if base_value else 0.0
                sign = "+" if day_pnl >= 0 else ""
                items.append({
                    "icon": "sparkles",
                    "label": "Your portfolio",
                    "text": f"{sign}${day_pnl:,.2f} today ({sign}{day_pct:.2f}% of ${base_value:,.0f})",
                    "tone": "positive" if day_pnl >= 0 else "negative",
                })
    except Exception as exc:  # noqa: BLE001
        log.warning("briefing portfolio calc failed: %s", exc)

    # 3. Risk-off — VIX
    if vix:
        regime = "calm" if vix["price"] < 20 else "elevated" if vix["price"] < 30 else "stressed"
        items.append({
            "icon": "alert_circle",
            "label": "Risk regime",
            "text": f"VIX at {vix['price']:.1f} — market is {regime}",
            "tone": "neutral" if vix["price"] < 20 else "warning",
        })

    # 4. Trending — top US gainer (skipped if user already holds it)
    trends = aux_results.get("trends")
    if isinstance(trends, dict):
        held = {h.ticker.upper() for h in non_cash}
        gainers = trends.get("top_gainers") or []
        pick = next((g for g in gainers if g.get("ticker") and g["ticker"].upper() not in held), None)
        if pick and pick.get("change_pct") is not None:
            items.append({
                "icon": "flame",
                "label": "Trending",
                "text": f"{pick['ticker']} +{pick['change_pct']:.1f}% today — top US gainer",
                "tone": "positive",
            })

    # 5. News — fresh headline for the user's biggest holding
    news = aux_results.get("news")
    if isinstance(news, list) and news and main_holding is not None:
        top_article = news[0]
        title = (top_article.get("title") or "").strip()
        if title:
            if len(title) > 110:
                title = title[:107] + "…"
            items.append({
                "icon": "newspaper",
                "label": f"News · {main_holding.ticker}",
                "text": title,
                "tone": "neutral",
                "url": top_article.get("url"),
            })

    # 6. Income — dividend signal on a held equity
    dividend = aux_results.get("dividend")
    if isinstance(dividend, dict) and div_ticker:
        yield_ = dividend.get("yield")
        safety = dividend.get("safety_score")
        rating = dividend.get("income_rating")
        if yield_ is not None and yield_ > 0:
            yld_pct = yield_ * 100 if yield_ < 1 else yield_
            bits = [f"{yld_pct:.2f}% yield"]
            if rating:
                bits.append(str(rating))
            if safety is not None:
                bits.append(f"safety {int(safety)}/100")
            items.append({
                "icon": "coins",
                "label": f"Income · {div_ticker}",
                "text": " · ".join(bits),
                "tone": "positive" if (rating or "").lower() in ("excellent", "good") else "neutral",
            })

    payload = {"items": items, "as_of": datetime.utcnow().isoformat() + "Z"}
    _BRIEFING_CACHE[user_id] = (time.time(), payload)
    return payload
