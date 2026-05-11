# Next Steps

This is the architecture skeleton — every file is in place, but most logic is `# TODO(impl)` stubs. Here's the priority queue to make it actually run end-to-end.

## 1. First boot (verify scaffold)

```bash
# Frontend deps
pnpm install

# Backend deps
cd backend
uv sync
cp .env.example .env
# fill in GEMINI_API_KEY (https://aistudio.google.com/apikey)
cd ..
```

Two terminals:
```bash
# Terminal 1
cd backend && uv run uvicorn app.main:app --reload --port 8765

# Terminal 2
pnpm tauri dev
```

Expected: window opens, sidebar shows "Coach online" green dot, dashboard renders, chat suggestions appear. Sending a message echoes back through the placeholder SSE stream.

## 2. Wire the supervisor to Gemini (the real first step)

`backend/app/agents/supervisor.py` currently uses a keyword router. Replace with a tool-aware Gemini call:

1. Bind tools from `app/tools/` to each agent via `langgraph.prebuilt.create_react_agent`
2. Make supervisor itself an LLM that picks the next agent
3. Stream events out of the graph (`graph.astream(...)`) and turn each chunk into an SSE event in `main.py`

## 3. Copy `stock-analysis` skill scripts

Copy these into `backend/app/legacy/`:
- `analyze_stock.py` → wired by `tools/market_tools.py::analyze_ticker_8dim`
- `dividends.py` → `get_dividend_metrics`
- `hot_scanner.py` → `scan_hot_trends`
- `rumor_scanner.py` → `scan_rumors`

Adjust imports (they may reference relative paths) and remove CLI argparse blocks.

## 4. Onboarding wizard

5 steps in `src/components/onboarding/`. Use `react-hook-form` + `zod` for validation. Persist to backend via a `POST /onboarding` endpoint.

## 5. Demo data seed

`backend/scripts/seed_demo_data.py` — generate 6 months of realistic transactions for "Alex Carter" persona using `faker`. Lets the dashboard show real numbers without manual entry during demo.

## 6. Live agent visualization

`src/components/chat/AgentGraph.tsx` using `reactflow`:
- 7 fixed nodes positioned in a hexagon
- SSE `agent_start` event → node glows
- SSE `agent_done` → node fades to "ok" state
- Edges animate when agent → tool calls happen

## 7. Multimodal PDF

Add `react-dropzone` to chat input. POST file → `/documents/upload` → backend reads bytes → Gemini `vision` model → returns parsed transactions for review.

## 8. Voice input

Mic button next to send button. Use `MediaRecorder` API → upload audio blob to a new `/audio/transcribe` endpoint → Gemini audio → text → fire normal chat flow.

## Risk: Tauri sidecar packaging (Day 4 decision)

If `pnpm tauri build` fails to bundle the Python interpreter, switch to the dev-mode demo (two terminals) for the hackathon. Documented in plan section 2 ("Pragmatic Fallback").
