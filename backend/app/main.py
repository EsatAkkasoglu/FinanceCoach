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
import uuid
from contextlib import asynccontextmanager
from datetime import date as date_cls, datetime
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage, AIMessage
from pydantic import BaseModel, Field
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.settings import configure_langsmith, settings
from app.db.models import Conversation, Goal, Holding, User
from app.db.session import SessionLocal, init_db
from app.agents.supervisor import AGENT_NODES, FINISH, SYNTHESIZER_NODE, build_supervisor
from app.routers.budget import router as budget_router
from app.routers.fx import router as fx_router
from app.services.document_processor.router import router as documents_router

log = logging.getLogger("fincoach")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

_GOOGLE_API_KEY_RE = re.compile(r"AIza[0-9A-Za-z_-]{20,}")


def _safe_error_message(exc: Exception) -> str:
    """Return a client-safe error without leaking provider API keys."""
    message = _GOOGLE_API_KEY_RE.sub("[REDACTED_GOOGLE_API_KEY]", str(exc))
    if "CONSUMER_SUSPENDED" in message or "has been suspended" in message:
        return (
            "Gemini API key is suspended. Create or rotate to a restricted Gemini API key "
            "for generativelanguage.googleapis.com, update backend/.env, and restart the backend."
        )
    return message


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("FinCoach starting up (demo_mode=%s)", settings.demo_mode)
    configure_langsmith()
    init_db()

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    async with AsyncSqliteSaver.from_conn_string(settings.db_path) as checkpointer:
        app.state.supervisor = build_supervisor(checkpointer=checkpointer)
        log.info("Supervisor graph built with AsyncSqliteSaver; ready on port %d", settings.port)

        import threading
        from app.tools.fund_tools import prewarm_universe
        threading.Thread(target=prewarm_universe, daemon=True, name="tefas-prewarm").start()
        log.info("TEFAS universe pre-warm scheduled in background")

        yield

    log.info("FinCoach shutting down")


app = FastAPI(title="FinCoach API", version="0.1.0", lifespan=lifespan)

# Tauri WebView2 origin is variable; allow all for local dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_router)
app.include_router(budget_router)
app.include_router(fx_router)


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
async def create_conversation(payload: dict):
    """Create a new conversation thread and return its metadata."""
    conv_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    title = (payload.get("title") or "").strip() or None
    now = datetime.utcnow()
    with SessionLocal() as db:
        conv = Conversation(
            id=conv_id,
            user_id=1,
            thread_id=thread_id,
            title=title,
            created_at=now,
            updated_at=now,
        )
        db.add(conv)
        db.commit()
    return {"id": conv_id, "thread_id": thread_id, "title": title, "created_at": now.isoformat()}


@app.get("/conversations")
async def list_conversations():
    """Return all non-archived conversations for the user, newest first."""
    with SessionLocal() as db:
        rows = db.execute(
            select(Conversation)
            .where(Conversation.user_id == 1, Conversation.archived == 0)
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
async def update_conversation(conv_id: str, payload: dict):
    """Update conversation title."""
    with SessionLocal() as db:
        conv = db.execute(select(Conversation).where(Conversation.id == conv_id)).scalar_one_or_none()
        if conv is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        if "title" in payload:
            conv.title = payload["title"]
        db.commit()
    return {"ok": True}


@app.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    """Archive (soft-delete) a conversation."""
    with SessionLocal() as db:
        conv = db.execute(select(Conversation).where(Conversation.id == conv_id)).scalar_one_or_none()
        if conv is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        conv.archived = 1
        db.commit()
    return {"ok": True}


# ── Chat ─────────────────────────────────────────────────────────────────────

@app.post("/chat")
async def chat(payload: dict):
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
    if not user_message:
        return {"error": "empty message"}
    if not thread_id:
        return {"error": "thread_id required"}

    supervisor = app.state.supervisor
    initial_state = {"messages": [HumanMessage(content=user_message)], "user_id": 1}
    config = {"configurable": {"thread_id": thread_id}}

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
        # Track which outer agent is currently executing so tool events
        # (which carry node='tools', not the outer node name) can be attributed.
        current_outer_agent: str | None = None
        # Each agent runs at most once per turn, but the supervisor runs
        # multiple times (once between every pair of agents). Track agents
        # that have already streamed so we don't double-emit.
        done_agents: set[str] = set()
        supervisor_started = False
        # Tool citations from every worker are aggregated and attached to
        # the synthesizer's final message, so the user sees one source list.
        collected_citations: list[dict] = []

        try:
            async for ev in supervisor.astream_events(initial_state, config=config, version="v2"):
                kind: str = ev["event"]
                name: str = ev.get("name", "")
                node: str = ev.get("metadata", {}).get("langgraph_node", "")
                data: dict = ev.get("data", {})

                # ── Supervisor iteration began ───────────────────────────
                if kind == "on_chain_start" and name == "supervisor":
                    yield _evt("agent_start", {"agent": "supervisor"})
                    supervisor_started = True

                # ── Supervisor iteration finished → emit its decision ────
                elif kind == "on_chain_end" and name == "supervisor" and supervisor_started:
                    supervisor_started = False
                    output = data.get("output") or {}
                    chosen = output.get("next_action") if isinstance(output, dict) else None
                    yield _evt("agent_done", {"agent": "supervisor"})
                    if chosen and chosen != FINISH and chosen in AGENT_NODES:
                        # Workers stay internal — UI shows activity (tools)
                        # but does NOT open a new bubble for them.
                        yield _evt("agent_start", {"agent": chosen, "internal": True})
                        final_agent = chosen
                    elif chosen == FINISH:
                        # Synthesizer owns the visible bubble.
                        yield _evt("agent_start", {"agent": SYNTHESIZER_NODE, "internal": False})
                        final_agent = SYNTHESIZER_NODE

                # ── Outer worker / synthesizer node started → track active
                elif kind == "on_chain_start" and (name in AGENT_NODES or name == SYNTHESIZER_NODE):
                    current_outer_agent = name

                # ── Real-time tool call ──────────────────────────────────
                elif kind == "on_tool_start" and node == "tools":
                    tool_input = data.get("input") or {}
                    yield _evt("tool_call", {
                        "tool": name,
                        "args": _safe_args(tool_input),
                        "agent": current_outer_agent or "",
                        "run_id": ev.get("run_id", ""),
                    })

                # ── Tool finished → result summary ───────────────────────
                elif kind == "on_tool_end" and node == "tools":
                    raw_output = data.get("output")
                    result_text = _summarize_tool_output(raw_output)
                    yield _evt("tool_result", {
                        "tool": name,
                        "result": result_text,
                        "run_id": ev.get("run_id", ""),
                    })

                # ── Worker node finished → collect citations, stay silent ─
                # Workers no longer emit `agent_message`/`token` directly;
                # the synthesizer will write the final user-facing reply.
                # Worker failures are logged + folded into the synthesizer
                # input as "(returned no reply)", which the synthesizer
                # acknowledges in natural language.
                elif kind == "on_chain_end" and name in AGENT_NODES and name not in done_agents:
                    done_agents.add(name)
                    current_outer_agent = None
                    output = data.get("output") or {}

                    if isinstance(output, dict):
                        err = output.get("error")
                        citations = output.get("citations") or []
                        msgs = output.get("messages") or []
                        content = ""
                        if msgs:
                            content = _normalize_content(getattr(msgs[-1], "content", ""))

                        if citations:
                            collected_citations.extend(
                                {**c, "agent": name} for c in citations
                            )

                        if err:
                            log.warning(
                                "worker %s errored (folded into synthesizer): %s/%s",
                                name, err.get("type"), err.get("message"),
                            )
                        elif not content:
                            log.warning(
                                "worker %s ended with no content (citations=%d) — synthesizer will note the gap",
                                name, len(citations),
                            )

                    yield _evt("agent_done", {"agent": name})

                # ── Synthesizer finished → emit the single visible reply ──
                elif kind == "on_chain_end" and name == SYNTHESIZER_NODE and name not in done_agents:
                    done_agents.add(name)
                    current_outer_agent = None
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
                            for tok in _chunked(content, 24):
                                yield _evt("token", {"text": tok})
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
                _touch_conversation(conv_id, user_message)
            yield _evt("done", {})

    return EventSourceResponse(event_stream())


def _touch_conversation(conv_id: str, first_message: str) -> None:
    """Update updated_at and auto-generate title from first message if missing."""
    with SessionLocal() as db:
        conv = db.execute(select(Conversation).where(Conversation.id == conv_id)).scalar_one_or_none()
        if conv is None:
            return
        conv.updated_at = datetime.utcnow()
        if not conv.title:
            conv.title = first_message[:60].strip()
        db.commit()


def _summarize_tool_output(output: object) -> str:
    """Return a short human-readable summary of a tool's return value."""
    if output is None:
        return "no result"
    text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, default=str)
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
async def onboarding(payload: OnboardingIn):
    """Persist the onboarding wizard output into the User / Goal / Holding tables.

    The default user (id=1) seeded by ``init_db`` is updated in place rather
    than creating a duplicate; the prototype is single-user.
    """
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.id == 1)).scalar_one_or_none()
        if user is None:
            user = User(id=1, name=payload.name)
            db.add(user)

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


def _quote_or_none(ticker: str) -> dict | None:
    """Wrap get_quote tool with safe error handling (briefing must never 500)."""
    try:
        from app.tools.market_tools import get_quote
        result = get_quote.invoke({"ticker": ticker})
        if "error" in result:
            return None
        return result
    except Exception as exc:  # noqa: BLE001
        log.warning("quote fetch failed for %s: %s", ticker, exc)
        return None


@app.get("/portfolio")
async def list_portfolio():
    """Return the user's holdings enriched with current price + P&L.

    Fetches all quotes in parallel via asyncio.gather + thread pool so N holdings
    cost ~1 round-trip instead of N sequential yfinance calls.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    with SessionLocal() as db:
        rows = db.execute(select(Holding).where(Holding.user_id == 1)).scalars().all()

    non_cash = [h for h in rows if h.asset_class != "cash"]

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=min(len(non_cash) or 1, 10)) as pool:
        quotes = await asyncio.gather(
            *[loop.run_in_executor(pool, _quote_or_none, h.ticker) for h in non_cash],
            return_exceptions=True,
        )
    quote_map = {
        h.ticker: (q if isinstance(q, dict) else None)
        for h, q in zip(non_cash, quotes)
    }

    enriched: list[dict] = []
    total_value = 0.0
    total_cost = 0.0

    for h in rows:
        cost_total = h.quantity * h.cost_basis
        if h.asset_class == "cash":
            current_price = 1.0
            current_value = h.quantity
            currency = "USD"
        else:
            quote = quote_map.get(h.ticker)
            current_price = quote["price"] if quote else h.cost_basis
            currency = (quote or {}).get("currency", "USD")
            current_value = h.quantity * current_price

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
            "currency": currency,
        })
        total_value += current_value
        total_cost += cost_total

    return {
        "holdings": enriched,
        "totals": {
            "value": round(total_value, 2),
            "cost": round(total_cost, 2),
            "pnl": round(total_value - total_cost, 2),
            "pnl_pct": round(((total_value - total_cost) / total_cost * 100.0) if total_cost else 0.0, 2),
            "count": len(enriched),
        },
    }


class HoldingCreate(BaseModel):
    ticker: str = Field(min_length=1, max_length=32)
    quantity: float = Field(gt=0)
    cost_basis: float = Field(default=0.0, ge=0)
    asset_class: Literal["stock", "crypto", "cash", "etf", "bond"] = "stock"


class HoldingUpdate(BaseModel):
    ticker: str | None = Field(default=None, min_length=1, max_length=32)
    quantity: float | None = Field(default=None, gt=0)
    cost_basis: float | None = Field(default=None, ge=0)
    asset_class: Literal["stock", "crypto", "cash", "etf", "bond"] | None = None


@app.post("/portfolio/holdings")
async def add_holding(payload: HoldingCreate):
    """Add a holding to the user's portfolio."""
    with SessionLocal() as db:
        h = Holding(
            user_id=1,
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
async def update_holding(holding_id: int, payload: HoldingUpdate):
    """Patch a single holding. Only fields present in the body are touched."""
    with SessionLocal() as db:
        h = db.execute(
            select(Holding).where(Holding.id == holding_id, Holding.user_id == 1)
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
async def delete_holding(holding_id: int):
    """Remove a holding."""
    with SessionLocal() as db:
        h = db.execute(
            select(Holding).where(Holding.id == holding_id, Holding.user_id == 1)
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
        "name": user.name,
        "avatar": user.avatar,
        "monthly_income": user.monthly_income,
        "risk_score": user.risk_score,
        "risk_profile": user.risk_profile,
        "roast_mode": bool(user.roast_mode),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@app.get("/profile")
async def get_profile():
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.id == 1)).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="profile not found")
        return _serialize_user(user)


@app.patch("/profile")
async def update_profile(payload: ProfileUpdate):
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.id == 1)).scalar_one_or_none()
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


@app.get("/briefing")
async def daily_briefing():
    """Personalized 3-bullet briefing for the dashboard widget.

    All yfinance calls run in parallel (S&P 500 + VIX + all holdings at once).
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    with SessionLocal() as db:
        holdings = db.execute(select(Holding).where(Holding.user_id == 1)).scalars().all()

    non_cash = [h for h in holdings if h.asset_class != "cash"]
    tickers_to_fetch = ["^GSPC", "^VIX"] + [h.ticker for h in non_cash]

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=min(len(tickers_to_fetch), 10)) as pool:
        results = await asyncio.gather(
            *[loop.run_in_executor(pool, _quote_or_none, t) for t in tickers_to_fetch],
            return_exceptions=True,
        )

    def _safe(r):
        return r if isinstance(r, dict) else None

    spx = _safe(results[0])
    vix = _safe(results[1])
    holding_quotes = {h.ticker: _safe(results[2 + i]) for i, h in enumerate(non_cash)}

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

    return {"items": items, "as_of": datetime.utcnow().isoformat() + "Z"}
