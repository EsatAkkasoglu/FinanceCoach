# FinCoach

> AI Finance Coach — a multi-agent Windows desktop assistant powered by Gemini + LangGraph.

## Stack

- **Frontend**: Tauri 2.0 + React + TypeScript + Tailwind + shadcn/ui
- **Backend**: Python FastAPI sidecar with LangChain + LangGraph (supervisor pattern, 7 agents)
- **LLM**: Google Gemini 2.0 Flash (function calling + multimodal)
- **Storage**: SQLite (portfolio, transactions, goals) + ChromaDB (RAG memory)

## Architecture

```
Tauri (React UI)  ⇄  Python sidecar (FastAPI + LangGraph)  ⇄  Gemini API
                                ↓
                     SQLite + ChromaDB (local)
```

The supervisor agent dispatches to 7 specialists:

| Agent | Role |
|-------|------|
| Market Data | Live prices, technicals, 8-dim analysis (wraps `stock-analysis` skill) |
| Portfolio | Holdings, risk, performance |
| Budget Coach | Spending analysis, savings, "roast mode" |
| News & Sentiment | Headlines, hot scanner, rumor scanner |
| Risk Profiler | Onboarding quiz + behavioral risk score |
| Memory (RAG) | Semantic recall over past chats and transactions |
| Document Parser | PDF bank statements → structured transactions |

## Setup

### Prerequisites
- Node.js 20+ and pnpm (`npm i -g pnpm`)
- Python 3.11+ and uv (`pip install uv`)
- Rust + Tauri prerequisites: https://tauri.app/start/prerequisites/

### Install
```bash
# Frontend
pnpm install

# Backend (uses uv lockfile)
cd backend
uv sync
cd ..
```

### Environment
Copy and fill in API keys:
```bash
cp backend/.env.example backend/.env
```

Required keys:
- `GEMINI_API_KEY` — https://aistudio.google.com/apikey (free)
- `NEWS_API_KEY` — https://newsapi.org/register (free dev tier)
- `LANGSMITH_API_KEY` — optional but recommended https://smith.langchain.com (free)

### Run (dev)
Two terminals:

```bash
# Terminal 1: backend
cd backend
uv run uvicorn app.main:app --reload --port 8765

# Terminal 2: full Tauri app
pnpm tauri dev
```

Once stable, Tauri spawns the Python sidecar automatically — but during dev keeping them split makes hot-reload nicer.

### Build (production MSI)
```bash
pnpm tauri build
```
Output: `src-tauri/target/release/bundle/msi/FinCoach_<version>_x64_en-US.msi`

## Project Structure

```
finance/
├── src/                    # React frontend
│   ├── components/         # UI components by domain
│   ├── lib/api.ts          # FastAPI client (fetch + SSE)
│   └── store/              # Zustand stores
├── src-tauri/              # Rust shell (sidecar spawn)
├── backend/
│   ├── app/
│   │   ├── main.py         # FastAPI entry
│   │   ├── agents/         # LangGraph supervisor + 7 specialists
│   │   ├── tools/          # LangChain tool wrappers
│   │   ├── db/             # SQLAlchemy models + session
│   │   └── legacy/         # Copied stock-analysis skill scripts
│   └── tests/
└── docs/
```

## Disclaimer

⚠️ This is a hackathon prototype. AI-generated suggestions are **not financial advice**. Consult a licensed advisor before making investment decisions.
