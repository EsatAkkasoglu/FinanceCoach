# FinCoach

<p align="center">
        <a href="https://fincoach-esat.web.app/"><strong>Try the live demo — https://fincoach-esat.web.app/</strong></a>
</p>

**FinCoach** is an AI-powered personal finance coach built as a Windows desktop application. It helps users understand their money, track their budget, manage financial goals, analyze portfolios, compare Turkish investment funds, and interact with a multi-agent finance assistant.

FinCoach is designed not only to display financial data, but also to interpret it through the user’s goals, risk profile, income structure, portfolio composition, and financial behavior.

> Hackathon prototype — AI-generated outputs are not financial advice.

---

## Overview

FinCoach combines a desktop finance dashboard with a multi-agent AI backend. Users can onboard by entering their financial goal, income sources, accounts, risk tolerance, and current holdings. The application then creates a personalized finance workspace that includes:

- net worth overview
- monthly income and expense tracking
- savings and cash-flow insights
- goal planning
- portfolio tracking
- Turkish investment fund discovery
- document-based financial data extraction
- AI chat with contextual memory
- risk-profile-aware coaching notes

The system is built around the idea of a **financial coach**, not just a tracker. It aims to answer questions such as:

- What is my current financial picture?
- How much should I save monthly to reach my goal?
- Is my portfolio aligned with my risk profile?
- Which funds or assets are worth exploring?
- What should my next best financial action be?
- What can be extracted from my bank statement, payslip, invoice, or portfolio document?

---

## Core Features

### 1. Personalized Onboarding

FinCoach begins with a guided onboarding flow that collects the user’s basic financial context:

- profile name and avatar
- primary financial goal
- target amount and deadline
- income sources
- accounts and balances
- behavioral risk profile
- starting portfolio

The onboarding data is used to personalize dashboards, budget insights, goal projections, and portfolio analysis.

---

### 2. Dashboard

The dashboard provides a high-level summary of the user’s financial situation.

Planned and implemented dashboard concepts include:

- net worth
- monthly income
- monthly expenses
- savings rate
- daily market brief
- asset allocation summary
- risk profile badge
- goal summary
- next best action card

The dashboard is intended to act as the user’s financial command center.

---

### 3. Portfolio

The portfolio module allows users to track holdings such as:

- stocks
- ETFs
- crypto assets
- cash
- bonds
- mutual funds
- Turkish funds
- gold or commodity-like assets

The goal is to help users understand:

- total portfolio value
- asset allocation
- concentration risk
- risk-profile fit
- goal alignment
- daily and historical changes

Portfolio data can be entered manually or described to the AI coach.

---

### 4. Budget

The budget module helps users track cash flow and understand where their money goes.

It includes:

- cash accounts
- income sources
- recurring income
- expenses
- subscriptions
- upcoming payments
- transactions
- document-based import options

The budget screen is designed to answer:

- How much money do I have?
- How much income is expected?
- What are my recurring expenses?
- What is my savings capacity?
- What data is missing before meaningful budget analysis can be made?

---

### 5. Turkish Funds

The Turkish Funds module focuses on local investment fund discovery and comparison.

It can support:

- TEFAS fund listings
- fund categories
- risk levels
- 1-month, 6-month, and 1-year returns
- category filters
- search by fund code or name
- risk-profile-aware suitability notes
- comparison basket
- risk-return analysis

This module is especially important for local financial relevance in Türkiye.

---

### 6. Discover

The Discover page is designed as a market discovery center.

It may include:

- market pulse
- trending assets
- trending crypto assets
- Turkish fund highlights
- news and catalysts
- macro calendar
- M&A and corporate event signals
- risk-profile-aware discovery notes
- watchlist actions

The goal is to help users make sense of what is happening in the market without presenting speculative assets as direct recommendations.

---

### 7. Goals

The Goals module helps users plan and track financial targets.

It supports concepts such as:

- target amount
- current saved amount
- remaining amount
- target date
- required monthly contribution
- contribution history
- goal feasibility
- next best action
- suggested contribution plan

Goals are connected to the user’s budget, cash position, risk profile, and portfolio strategy.

---

### 8. Documents

The Documents module is designed to extract structured financial information from uploaded files.

Supported document concepts include:

- bank statements
- payslips
- portfolio statements
- invoices
- receipts
- credit card statements
- subscription documents

The document parser can extract:

- accounts
- income
- expenses
- transactions
- holdings
- subscriptions
- payment dates
- categories

Users should be able to review extracted data before saving it.

---

### 9. Settings

The Settings section manages user preferences and application behavior:

- AI and API keys
- model selection
- temperature / creativity
- language
- dark mode
- demo mode
- coaching behavior
- profile avatar
- risk profile
- reset / dangerous zone

Settings are intended to function as a trust and control center for the user.

---

## AI Architecture

FinCoach uses a multi-agent architecture built around a supervisor pattern.

The supervisor routes user requests to specialized agents depending on the task.

| Agent | Role |
|------|------|
| Market Data Agent | Live prices, technical indicators, market data, 8-dimensional analysis |
| Portfolio Agent | Holdings, allocation, portfolio risk, performance |
| Budget Coach | Income, expenses, savings, cash flow and spending behavior |
| News & Sentiment Agent | Headlines, trend detection, market catalysts |
| Risk Profiler | Risk questionnaire and behavioral risk scoring |
| Memory Agent | Semantic recall over past chats and financial context |
| Document Parser | Extracts structured data from financial documents |

---

## Tech Stack

### Frontend

- Tauri 2
- React
- TypeScript
- Tailwind CSS
- shadcn/ui
- Zustand

### Backend

- Python
- FastAPI
- LangChain
- LangGraph
- SQLAlchemy
- SQLite
- ChromaDB

### AI / LLM

- Google Gemini
- Function calling
- Multimodal document understanding
- Agentic orchestration through LangGraph

### Local Storage

- SQLite for structured financial data
- ChromaDB for semantic memory and retrieval

---

## System Architecture

```text
Tauri Desktop App
        |
        v
React + TypeScript UI
        |
        v
FastAPI Python Sidecar
        |
        v
LangGraph Supervisor Agent
        |
        +--> Market Data Agent
        +--> Portfolio Agent
        +--> Budget Coach
        +--> News & Sentiment Agent
        +--> Risk Profiler
        +--> Memory Agent
        +--> Document Parser
        |
        v
SQLite + ChromaDB + External APIs
________________________________________
Data Sources and APIs
FinCoach may use the following services depending on configuration:
•	Gemini API for AI reasoning and multimodal analysis
•	NewsAPI for news and sentiment
•	TEFAS-related data for Turkish investment funds
•	market data providers such as yfinance or similar sources
•	local SQLite database for user data
•	local ChromaDB store for semantic memory
API keys are configured locally through environment variables or settings.
________________________________________
Setup
Prerequisites
Install the following tools:
•	Node.js 20+
•	pnpm
•	Python 3.11+
•	uv
•	Rust
•	Tauri Windows prerequisites
•	Microsoft C++ Build Tools on Windows
Useful commands:
npm i -g pnpm
pip install uv
For Tauri prerequisites, see:
https://tauri.app/start/prerequisites/
________________________________________
Installation
Clone the repository:
git clone https://github.com/EsatAkkasoglu/FinanceCoach.git
cd FinanceCoach
Install frontend dependencies:
pnpm install
Install backend dependencies:
cd backend
uv sync
cd ..
________________________________________
Environment Variables
Copy the example environment file:
cp backend/.env.example backend/.env
Fill in the required API keys:
GEMINI_API_KEY=your_gemini_api_key_here
NEWS_API_KEY=your_news_api_key_here

LANGSMITH_API_KEY=your_langsmith_api_key_here
LANGSMITH_TRACING=false
LANGSMITH_PROJECT=fincoach-hackathon

FINCOACH_PORT=8765
FINCOACH_DB_PATH=./fincoach.db
FINCOACH_CHROMA_PATH=./chroma_db
FINCOACH_DEMO_MODE=false

GEMINI_MODEL=gemini-3.1-flash-lite
GEMINI_TEMPERATURE=0.3
Required
•	GEMINI_API_KEY
Optional
•	NEWS_API_KEY
•	LANGSMITH_API_KEY
If an optional API key is missing, the related agent or feature may remain inactive or fall back to demo behavior.
________________________________________
Running in Development
Use two terminals during development.
Terminal 1 — Backend
cd backend
uv run uvicorn app.main:app --port 8765
The API will be available at:
http://127.0.0.1:8765
FastAPI docs:
http://127.0.0.1:8765/docs
Terminal 2 — Tauri App
pnpm tauri dev
________________________________________
Build
To build the production desktop application:
pnpm tauri build
The Windows installer will be generated under:
src-tauri/target/release/bundle/
________________________________________
Project Structure
FinanceCoach/
├── backend/
│   ├── app/
│   │   ├── agents/
│   │   ├── auth/
│   │   ├── db/
│   │   ├── tools/
│   │   ├── main.py
│   │   └── settings.py
│   ├── tests/
│   ├── .env.example
│   └── pyproject.toml
│
├── src/
│   ├── components/
│   ├── lib/
│   ├── store/
│   └── main.tsx
│
├── src-tauri/
│   ├── src/
│   ├── Cargo.toml
│   └── tauri.conf.json
│
├── docs/
├── package.json
├── pnpm-lock.yaml
└── README.md
________________________________________
Security and Privacy Notes
FinCoach handles sensitive financial information. The product should follow these principles:
•	API keys should never be committed to Git.
•	.env files must remain local.
•	Users should review extracted document data before saving.
•	Financial documents should be deletable by the user.
•	Sensitive fields such as account numbers or identity numbers should be masked where possible.
•	Demo mode should be clearly labeled when active.
•	AI-generated outputs must be clearly separated from licensed financial advice.
________________________________________
Financial Disclaimer
FinCoach is a hackathon prototype.
The application may generate AI-based financial summaries, portfolio comments, budget insights, market observations and goal suggestions. These outputs are for informational and educational purposes only.
They do not constitute:
•	financial advice
•	investment advice
•	portfolio management
•	legal advice
•	tax advice
•	regulated suitability assessment
Users should consult a licensed financial advisor before making investment decisions.
________________________________________
Roadmap
Potential improvements:
•	Better dashboard data consistency
•	Risk-profile-aware fund and asset suitability
•	Portfolio concentration analysis
•	Goal feasibility scoring
•	Document review and approval workflow
•	Turkish fund comparison basket
•	Risk-return visualization
•	Watchlist
•	Better localization
•	Data export/import
•	Privacy and data retention controls
•	Demo-safe mode for presentations
________________________________________
Team / Credits
Built for hackathon demonstration purposes by the FinCoach team.

---
