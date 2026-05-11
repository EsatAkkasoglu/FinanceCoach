"""Multi-agent system. Supervisor delegates to 7 specialists.

Agent inventory:
    market_data       — live prices, technicals, 8-dim analysis
    portfolio          — holdings, performance, sector concentration
    budget_coach       — spending analysis, savings, roast mode
    news_sentiment     — headlines, hot scanner, rumor scanner
    risk_profiler      — quiz scoring + behavioral risk inference
    memory             — RAG over chat history + transactions (ChromaDB)
    document_parser    — Gemini multimodal PDF/image → structured tx
"""
