# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 🔑 NotebookLM Knowledge Source — ZORUNLU

Kripto türev araçlarıyla ilgili **her türlü sohbet, soru veya kodlama görevinden önce** aşağıdaki adımlar uygulanır:

1. **Önce NotebookLM'e sor:** `mcp__notebooklm__ask_question` aracını kullan, notebook ID: `a-comprehensive-guide-to-crypt`
2. **Gelen cevabı referans al:** NotebookLM'den dönen bilgiyi temel alarak açıklama yap veya kod yaz
3. **Sonra kodla:** NotebookLM cevabına dayanarak implementasyona geç

**Notebook:** A Comprehensive Guide to Crypto Derivatives · **ID:** `a-comprehensive-guide-to-crypt`
Kapsam: futures, options, perpetual swaps, funding rate, liquidation, margin, DeFi türevleri, risk yönetimi.
Bu adım atlanamaz — kullanıcı kripto türev konusunda bir şey sorarsa, kod yazılacaksa veya feature eklenecekse.

## Working style — agentic, self-querying (kullanıcının açık tercihi)

Bu repoda istemlere **tek-geçişli, "olur herhalde" cevaplarla değil, sorgulayıcı/agentic bir döngüyle** karşılık ver. Çalışma şekli:

1. **Anchor.** "Doğru ve bitmiş" ne demek, tek cümleyle yaz.
2. **Üret** (kod/plan/cevap).
3. **Self-query.** Ürettiğini hedef tahtasına koy; onu *yanlış çıkaracak* 4–8 spesifik, saldırgan soru sor.
4. **Kanıtla** — soruları hafızadan değil; dosya okuyarak, komut çalıştırarak, grep'leyerek cevapla (✅/⚠️/❓).
5. **Düzelt ve converge** — açıkları kapat, kalan riski dürüstçe raporla.

İki skill bu tarzı uygular — birlikte tam döngü:

- **`/team-council`** — *ihtiyacı anla.* Ciddi, belirsiz veya açık-uçlu bir istemde, gerçek subagent'lerden oluşan bir takım (PM, Mimar, Frontend/3D, QA) **birbirine soru sorarak** asıl ihtiyacı kazır, gereken yerde sana net sorular sorar ve ortak bir anlayış + plana yakınsar. Tam tartışma transkripti gösterilir.
- **`/self-query`** — *işi doğrula.* Ürettiğin çıktıyı kendine sorularla dövüp kanıtla (dosya/komut/grep) doğrula, açıkları kapat, converge et.

Akış: ciddi/belirsiz istem → `/team-council` ile ihtiyacı netleştir → uygula → `/self-query` ile doğrula. **Kod değişikliğini gerçek kontrolleri (ruff/pytest/tsc) çalıştırmadan "bitti" sayma.** Mimariyle ilgili bir iddiada bulunmadan önce CLAUDE.md'ye değil **koda** bak; bu dosyadaki notlar bile zamanla bayatlayabilir.

## What this is

AI finance coach. Two processes that talk over HTTP + SSE:

```
Tauri WebView2 (React/TS UI :1420)  ⇄  FastAPI sidecar (:8765)  ⇄  Google Gemini
                                              ↓
                                    SQLite (fincoach.db) + ChromaDB (chroma_db/)
```

Dual deployment target: packaged **Tauri desktop app** *and* **Cloud Run** (sidecar as a service) with Neon Postgres / Firebase Auth. Anything relying on an in-process startup thread or timer (TEFAS pre-warm, news collector) silently won't fire on Cloud Run with `min-instances=0` — needs an external trigger there.

## Front end — the primary surface (3D / motion / motion graphics)

**The front end is where this project invests the most care, and the quality bar for 3D and motion is high.** Treat animation, motion graphics, and the WebGL layer as first-class product surface, not decoration — but never at the cost of first paint, frame budget, or accessibility.

**3D is imperative Three.js (r184), not react-three-fiber.** The whole 3D layer routes through one shared lifecycle harness — read it before touching any scene:

- `src/lib/three/mountScene.ts` — `mountScene(el, build, opts)` owns the boilerplate every ambient canvas needs: `WebGLRenderer` (alpha, `powerPreference: high-performance`, DPR capped at 1.75), a rAF loop with **clamped delta** (no giant jump when returning from a hidden tab), **pause while the tab is hidden** (visibility API), **ResizeObserver** resize (panels resize with sidebar collapse, not just window), and full teardown. Your `build({scene, camera, renderer, ...})` returns `{ onFrame?, dispose? }` — and `dispose` **must** free every geometry/material/texture you created (GPU leaks otherwise). `makeGlowSprite()` is the shared particle texture.
- Scenes live in `src/components/three/` (`AmbientField3D`, `WealthWave3D`, `HeroOrb3D`) and `src/components/landing/` (`LandingBackground3D`, `HeroVisual`). New 3D goes through `mountScene` — don't hand-roll a renderer/rAF/teardown.

**Non-negotiable motion conventions** (already enforced across ~18 components — keep them):

- **Respect reduced motion.** Gate animations behind framer-motion's `useReducedMotion()`; the ambient WebGL backdrop in `App.tsx` is *not even mounted* when reduce-motion is on. New motion must honor this.
- **Never block first paint.** Heavy 3D is `React.lazy()` + code-split and wrapped in `<Suspense fallback={null}>` (see `AmbientField3D` in `App.tsx`). Keep ambient/decorative WebGL off the critical path.
- **Motion stack:** `framer-motion` for component/page transitions (page content uses `<AnimatePresence mode="wait">` keyed by the top-level route segment so `/chat/a ↔ /chat/b` doesn't re-animate), `anime.js` v4 for fine-grained timeline/stagger work (an `animejs` skill is installed for v4 specifics), `three` for WebGL.

**App shell & routing** (`src/App.tsx` is the single composition root):

- **Language-prefixed routes** via react-router v7: every app route is `/:lang/...` (`en`/`tr`). Use the helpers in `src/lib/routing.ts` (`buildLocalizedPath`, `getLanguageFromPath`, `stripLanguagePrefix`, `isSupportedLanguage`) — don't build URLs by hand or you'll drop the language prefix. i18n is `i18next`/`react-i18next` with per-feature namespaces.
- **Auth gating happens in `App.tsx`**, in order: not-`ready` → splash; no `user` → marketing `LandingPage` (or `AuthPage` on `/login`,`/register`); `user` without `has_onboarded` → `OnboardingWizard`; else the app. Session is restored via Firebase `onIdTokenChanged` with an 8s cold-start cap, plus a demo-token path (`DEMO_TOKEN_KEY`). A 401 from any API call drops the user to login (`onUnauthorized`).
- **State:** Zustand stores in `src/store/index.ts` (`useAuthStore`, `useConversationStore`, `useUserStore`, `useTourStore`).
- **Theming:** Tailwind + shadcn-style primitives in `components/ui/`, colors via CSS custom properties — always `hsl(var(--surface))`, `hsl(var(--border))`, `hsl(var(--text))`, `hsl(var(--accent))`, etc. Don't hardcode hex; use the token vars so light/dark and theming hold.
- **Backend client:** `src/lib/api.ts` is the only place that talks to FastAPI (typed fetch wrappers + the SSE parser). Charts use `recharts`; the live agent graph uses `reactflow`; forms use `react-hook-form` + `zod`; toasts via `sonner`.

## Backend architecture (the part worth reading multiple files for)

**The supervisor is a parallel map-reduce graph, not one-specialist-per-turn.** (Older notes say "single specialist per turn" — that is stale; verify in `backend/app/agents/supervisor.py`.) Per user turn:

```
START → strategist (one plan() call) → Send fan-out to N specialists IN PARALLEL
      → gather (sync barrier, findings merged via a state reducer)
      → advisor (conditional: only when the plan requires allocation/synthesis)
      → synthesizer (always writes the single user-facing reply) → END
```

- **Public API of `supervisor.py`:** `AGENT_NODES` (name→`run` callable map of the 7 specialists: market_data, portfolio, budget_coach, news_sentiment, risk_profiler, memory, document_parser), the `SpecialistName` Literal, and the node-name constants `STRATEGIST_NODE` / `GATHER_NODE` / `ADVISOR_NODE` / `SYNTHESIZER_NODE`. There is **no** `ROUTER_SYSTEM_PROMPT` or `AgentName`. Each specialist is a LangGraph `create_react_agent(get_llm(), tools=[...], prompt=...)`.
- **Streaming:** `/chat` is SSE driven by `astream_events(version="v2")`. The handler in `main.py` already copes with interleaved worker events from the parallel specialists — it tracks completion via a `done_nodes` set against `INTERNAL_NODES = {STRATEGIST_NODE, ADVISOR_NODE, *AGENT_NODES.keys()}`. If you change the graph shape (nodes, parallelism, the barrier), self-query the *event stream*, not just the node.
- **Deterministic calc layer:** `backend/app/tools/calc_tools.py` + `_calc_result.py` hold pure-Python finance math (FV/goal contribution via numpy-financial, portfolio summary/concentration/drift, returns, correlation, instrument comparison). They return a standard envelope `{ok, raw_value, formatted_value, formula, ui_type, data}` so the LLM never does arithmetic — the frontend renders it via `src/components/chat/CalcResultCard.tsx`. Bound to portfolio/budget_coach/market_data.
- **Quant layer:** `backend/app/quant/` is pure computation — no DB, no network, no LangChain. `data.py` (price loading + alignment; owns `close_map`, which `calc_tools` imports), `backtest.py` (vectorised price-path backtest, walk-forward, purged/embargoed folds), `risk.py` (VaR/CVaR/EWMA/beta/factor OLS), `optimize.py` (Ledoit-Wolf, min-var, max-Sharpe, risk parity, frontier), `options.py` (BSM + greeks + implied vol + Merton jumps). It **imports** its risk-adjusted metrics from `app/eval/scorecard.py` rather than redefining them, and its TA from `tools/crypto_short_term.py`. The `@tool` wrappers live in `tools/quant_tools.py` (bound into the `portfolio` and `market_data` desks — no graph change) and the page-facing REST surface in `routers/quant.py`. **scipy is used in exactly three places** (SLSQP for long-only mean-variance, brentq for implied vol, `stats.t` for regression t-stats); `scorecard.py` keeps its hand-rolled normal CDF/PPF deliberately. Library evaluation and rejection rationale: `docs/QUANT_STACK.md`.
- **SSE payload cap:** `main._summarize_tool_output` truncates every tool result at **4000 characters**, and `src/lib/parseToolResult.ts` degrades a truncated envelope to plain text *silently* — a too-large payload doesn't error, the card just stops rendering. Any tool returning a series must downsample (see `quant_tools._MAX_CURVE_POINTS = 80`, mirroring `calc_tools._MAX_HOLDINGS_IN_DATA = 12`). `tests/test_quant_tools.py` asserts the envelope stays under the cap.
- **Persistence:** LangGraph `AsyncSqliteSaver` checkpointer keyed by `thread_id`; message history reloads per conversation automatically.
- **Safety:** `_safe_error_message` in `main.py` redacts Google API keys from anything sent to the client — every new error path must go through it. `_normalize_content` handles Gemini 3.x `content` that arrives as a list of structured parts (never assume `content` is a string).

## Commands

Frontend (pnpm, repo root):

```
pnpm install
pnpm dev                         # Vite only (no Tauri, no window.__TAURI__)
pnpm tauri dev                   # full desktop app (needs Rust + Tauri prereqs)
pnpm lint                        # tsc --noEmit (type check — this is "lint")
pnpm test                        # vitest run
pnpm test src/lib/parseToolResult.test.ts   # single test file
pnpm exec vitest run -t "renders"           # single test by name
pnpm build                       # tsc -b && vite build
pnpm tauri build                 # MSI in src-tauri/target/release/bundle/msi/
```

Backend (uv, from `backend/`):

```
uv sync
uv run uvicorn app.main:app --reload --port 8765
uv run pytest                              # all
uv run pytest -m "not network"            # skip live-API hits (yfinance/NewsAPI/CoinGecko)
uv run pytest tests/test_x.py::test_y      # single test
uv run pytest -k "funding"                 # single test by keyword
uv run ruff check .
```

Dev workflow: two terminals (backend `uvicorn` + `pnpm tauri dev`). Sidecar auto-spawn is only for the packaged build.

## Conventions

- **Python**: 3.11+, `from __future__ import annotations` at top of modules, ruff `select = [E,F,I,W,N,UP,B]` with `ignore = ["E501"]` (line-length 100 set but not enforced), Pydantic v2 for request/response, SQLAlchemy 2.x `select()` style.
- **TypeScript**: strict, ESM, React 18. Tailwind + shadcn/ui (Radix in `components/ui/`), Zustand, `react-hook-form` + `zod`, `recharts`, `reactflow`, `framer-motion`, `sonner`. Path alias `@/` → `src/`.
- **Single-user prototype**: everything is hardcoded to `user_id=1`. Don't add multi-tenant data flows unless asked (Firebase Auth gates *access*, not per-user data isolation).
- **CORS** is wide-open (`*`) — fine for the local Tauri WebView2; do not ship as a public service that way.

## Adding to the system

- **New specialist:** module under `backend/app/agents/` exposing `run`; register in `AGENT_NODES`; add the name to the `SpecialistName` Literal; teach the strategist's planning prompt about it so it gets dispatched.
- **New tool:** `@tool`-decorated fn under `backend/app/tools/`, bound into the relevant agent's `create_react_agent(tools=[...])`. Args/returns must be **JSON-serializable** — the SSE layer JSON-dumps tool I/O (no `Decimal`, `datetime`, sets, custom objects raw).
- **New endpoint:** `main.py` or a router under `app/routers/`, then a typed wrapper in `src/lib/api.ts`.
- **New `ui_type`:** touches **two** files that must stay in sync — the `UiType` Literal in `backend/app/tools/_calc_result.py` and the `CalcEnvelope["ui_type"]` union in `src/components/chat/CalcResultCard.tsx`, plus a render branch in that component. Adding it on only one side fails silently (the card renders nothing). `CitationChip.tsx` needs no change — it dispatches on envelope shape, not tool name.
- **New 3D scene / motion:** go through `mountScene`, gate on `useReducedMotion`, lazy-load if decorative, dispose all GPU resources.
- **DB schema change:** edit `app/db/models.py`. Alembic is in deps but not wired — the current reset path is deleting `fincoach.db` and letting `init_db()` recreate it. **Confirm with the user before deleting** the DB or `chroma_db/`.

## External deps & keys

`backend/.env` (copy from `.env.example`): `GEMINI_API_KEY` (required), `NEWS_API_KEY` (news_sentiment), `LANGSMITH_API_KEY` (optional tracing). Frontend Firebase config in `src/lib/firebase.ts` / env. Live data sources: yfinance, NewsAPI, TEFAS (Turkish funds, pre-warmed in a background thread on startup), SEC EDGAR via `edgartools`, fear-and-greed. Roadmap notes in `docs/NEXT_STEPS.md`.

Never commit `fincoach.db*`, `chroma_db/`, `backend/.env`, or vendored model artifacts.

## Disclaimer

Hackathon prototype — outputs are **not** financial advice. Don't add features that imply they are.
