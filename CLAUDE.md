# FinCoach — Claude Project Guide

## 🔑 NotebookLM Knowledge Source — ZORUNLU

Kripto türev araçlarıyla ilgili **her türlü sohbet, soru veya kodlama görevinden önce** aşağıdaki adımlar uygulanır:

1. **Önce NotebookLM'e sor:** `mcp__notebooklm__ask_question` aracını kullan, notebook ID: `a-comprehensive-guide-to-crypt`
2. **Gelen cevabı referans al:** NotebookLM'den dönen bilgiyi temel alarak açıklama yap veya kod yaz
3. **Sonra kodla:** NotebookLM cevabına dayanarak implementasyona geç

**Notebook:** A Comprehensive Guide to Crypto Derivatives  
**URL:** https://notebooklm.google.com/notebook/f329eda7-a38a-47bc-866a-a11ee04c2297  
**Notebook ID:** `a-comprehensive-guide-to-crypt`

Kapsam: futures, options, perpetual swaps, funding rate, liquidation, margin, DeFi türevleri, risk yönetimi.  
Bu adım; kullanıcı kripto türev konusunda bir şey sorarsa, bu konuda kod yazılacaksa veya bir feature eklenecekse **atlanamaz.**

AI finance coach as a Windows desktop app. Tauri (React/TS) shell + Python FastAPI sidecar running a LangGraph supervisor over 7 specialist agents, all backed by Google Gemini.

## Architecture

```
Tauri (React UI :1420)  ⇄  FastAPI sidecar (:8765)  ⇄  Gemini API
                                    ↓
                          SQLite (fincoach.db) + ChromaDB (chroma_db/)
```

- **Supervisor**: LLM-first router (Gemini structured output) with keyword fallback. Dispatches a single specialist per turn — no parallel orchestration yet.
- **Streaming**: `/chat` is SSE via `astream_events(version="v2")`. Events: `agent_start`, `agent_done`, `tool_call`, `tool_result`, `citations`, `agent_message`, `token`, `done`, `error`.
- **Persistence**: LangGraph `AsyncSqliteSaver` checkpointer keyed by `thread_id` — message history reloads automatically per conversation.

## Layout

```
src/                    React frontend
  components/{chat,dashboard,onboarding,portfolio,settings,ui}/
  lib/api.ts            FastAPI client (fetch + SSE parser)
  store/index.ts        Zustand store
src-tauri/              Rust shell (sidecar spawn, tauri.conf.json)
backend/
  app/
    main.py             FastAPI app + lifespan + endpoints
    settings.py         pydantic-settings (env, model, paths)
    agents/             supervisor.py + 7 specialists, llm.py, state.py
    tools/              LangChain @tool wrappers (market, portfolio, news, fund, memory, user, symbol_resolver)
    routers/budget.py
    services/document_processor/   Multimodal PDF → transactions (google-genai SDK)
    db/{models,session}.py         SQLAlchemy 2.x + init_db
    legacy/             Vendored stock-analysis skill scripts
  tests/                pytest (markers: network, slow)
  pyproject.toml        uv-managed; ruff (line 100, py311)
docs/NEXT_STEPS.md
```

## Commands

Frontend (pnpm, run from repo root):
```
pnpm install
pnpm dev              # Vite only
pnpm tauri dev        # full desktop app (spawns sidecar in prod, not in dev)
pnpm lint             # tsc --noEmit
pnpm test             # vitest run
pnpm tauri build      # MSI in src-tauri/target/release/bundle/msi/
```

Backend (uv, run from `backend/`):
```
uv sync
uv run uvicorn app.main:app --reload --port 8765
uv run pytest                             # all
uv run pytest -m "not network"            # skip live API hits
uv run ruff check .
```

Dev workflow: keep two terminals (backend + `pnpm tauri dev`). Sidecar auto-spawn is for the packaged build.

## Conventions

- **Python**: 3.11+, ruff (E,F,I,W,N,UP,B; ignore E501), `from __future__ import annotations` at top of modules. Pydantic v2 models for request/response. SQLAlchemy 2.x `select()` style.
- **TypeScript**: strict, ESM, React 18, Tailwind + shadcn/ui (Radix primitives in `components/ui/`), Zustand for state, `react-hook-form` + `zod` for forms, `recharts` for charts, `reactflow` for the agent graph viz, `framer-motion` for animation, `sonner` for toasts.
- **Single-user prototype**: everything is hardcoded to `user_id=1`. Don't add auth flows unless asked.
- **API key safety**: `_safe_error_message` in `main.py` redacts Google API keys from any error surfaced to the client — preserve that whenever adding new error paths.
- **CORS**: wide-open (`*`) — fine for local Tauri WebView2, do not ship as a public service.

## Adding to the system

- **New agent**: add module under `backend/app/agents/`, register in `AGENT_NODES` and `AgentName` Literal in `supervisor.py`, update `ROUTER_SYSTEM_PROMPT`.
- **New tool**: `@tool`-decorated function under `backend/app/tools/`, then bind it in the relevant agent's `create_react_agent` call. Tool args/outputs must be JSON-serializable (the SSE layer JSON-dumps them).
- **New endpoint**: add to `main.py` or a new router under `app/routers/`, then a typed wrapper in `src/lib/api.ts`.
- **DB schema change**: edit `app/db/models.py`. Alembic is in deps but not yet wired — for the prototype, deleting `fincoach.db` and letting `init_db()` recreate is the current path. Confirm with the user before deleting.

## External deps & keys

`backend/.env` (copy from `.env.example`):
- `GEMINI_API_KEY` — required
- `NEWS_API_KEY` — for news_sentiment agent
- `LANGSMITH_API_KEY` — optional tracing (`configure_langsmith()` reads it)

Live data sources: yfinance, NewsAPI, TEFAS (Turkish funds, pre-warmed in a background thread on startup), SEC EDGAR via `edgartools`, fear-and-greed.

## Gotchas

- Tests marked `network` hit live APIs — skip in CI with `-m "not network"`.
- The supervisor prompt assumes one agent per turn; if you change that, the SSE event ordering in `main.py` (`done_agents` set, `current_outer_agent` tracking) needs to handle interleaved worker events.
- LangChain message `content` can be a list of structured parts (Gemini 3.x) — always run through `_normalize_content` before treating as a string.
- `pnpm tauri dev` requires Rust + the Tauri prerequisites installed; the Vite dev server alone (`pnpm dev`) is fine for pure UI iteration but won't have `window.__TAURI__`.
- Do not commit `fincoach.db*`, `chroma_db/`, `backend/.env`, or any vendored model artifacts.

## Disclaimer

Hackathon prototype — outputs are not financial advice. Don't add features that imply they are.
