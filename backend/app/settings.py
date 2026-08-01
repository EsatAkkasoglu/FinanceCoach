"""Application settings loaded from environment / .env file."""
from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Default JWT secret — only acceptable for local/dev. Cloud Run startup refuses
# to boot with this value (see the lifespan guard in main.py).
DEFAULT_JWT_SECRET = "dev-secret-change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API keys
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    news_api_key: str = Field(default="", alias="NEWS_API_KEY")
    langsmith_api_key: str = Field(default="", alias="LANGSMITH_API_KEY")
    # Macro / context feeds (all optional — the signal engine degrades to
    # price-action when a feed/key is absent). FRED: free key for treasury yields,
    # the 10y-2y curve, fed funds. Finnhub: free 60/min equity quotes + funda +
    # per-ticker news. Crypto Fear & Greed (alternative.me) is keyless.
    fred_api_key: str = Field(default="", alias="FRED_API_KEY")
    finnhub_api_key: str = Field(default="", alias="FINNHUB_API_KEY")
    # CoinDesk Data API (formerly CryptoCompare) — primary crypto data source:
    # spot/index prices, OHLCV history, top-by-market-cap, and derivatives
    # (funding rate, open interest). https://developers.coindesk.com
    coindesk_api_key: str = Field(default="", alias="COINDESK_API_KEY")
    # RapidAPI gateway key. Each RapidAPI product needs its own subscription —
    # an unsubscribed one returns 403 even with a valid key (see services/rapidapi.py).
    rapidapi_key: str = Field(default="", alias="RAPIDAPI_KEY")
    # Default derivatives venue for funding-rate / open-interest lookups.
    coindesk_futures_market: str = Field(default="binance", alias="COINDESK_FUTURES_MARKET")
    # Curated short-term crypto basket — chosen so BOTH news analysis (heavy,
    # continuous coverage) and technical/derivatives analysis (deep perpetual
    # markets: funding + open interest) are available. Drives the 4-hour signal
    # scan and the demo account's seeded targets.
    crypto_short_term_basket: str = Field(default="BTC,ETH,SOL", alias="FINCOACH_CRYPTO_BASKET")

    @property
    def crypto_basket(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for raw in self.crypto_short_term_basket.split(","):
            sym = raw.strip().upper()
            if sym and sym not in seen:
                seen.add(sym)
                out.append(sym)
        return out
    # Server
    port: int = Field(default=8765, alias="FINCOACH_PORT")

    # Storage
    db_path: str = Field(default="./fincoach.db", alias="FINCOACH_DB_PATH")
    database_url: str = Field(default="", alias="DATABASE_URL")   # Neon PostgreSQL URL; falls back to SQLite
    chroma_path: str = Field(default="./chroma_db", alias="FINCOACH_CHROMA_PATH")

    # Behavior flags
    demo_mode: bool = Field(default=False, alias="FINCOACH_DEMO_MODE")

    # Admin allowlist (comma-separated usernames). Empty = admin endpoints disabled.
    admin_usernames: str = Field(default="", alias="FINCOACH_ADMIN_USERNAMES")

    # News collector — background poller that fetches + enriches headlines into
    # the news_articles table so /chat and the dashboard read pre-computed
    # results (ms-level) instead of hitting feeds on every request.
    #
    # Deployment note: keep this enabled everywhere, including Cloud Run. The
    # in-process scheduler polls ~15s after each cold start and every interval
    # while the instance is warm; a fully-idle (scaled-to-zero) instance simply
    # isn't serving anyone. GET /news/feed additionally triggers a background
    # stale-refresh, so a user opening the app after a long idle gets fresh news.
    # For a guaranteed cadence regardless of traffic, also point Cloud Scheduler
    # at POST /news/poll. On the desktop sidecar the process is always running.
    news_collector_enabled: bool = Field(default=True, alias="FINCOACH_NEWS_COLLECTOR_ENABLED")
    news_poll_minutes: int = Field(default=10, alias="FINCOACH_NEWS_POLL_MINUTES")
    # Comma-separated standing RSS feed URLs. Source name is derived from each
    # feed's channel title, so only URLs are needed here.
    news_feeds: str = Field(
        default=(
            "https://www.coindesk.com/arc/outboundfeeds/rss/,"
            "https://cointelegraph.com/rss,"
            "https://tr.investing.com/rss/news.rss,"
            "https://www.ntv.com.tr/ekonomi.rss"
        ),
        alias="FINCOACH_NEWS_FEEDS",
    )
    # Gemini batch enrichment (sentiment + category + 1-line summary). Disable to
    # store raw headlines only (zero LLM cost / quota use).
    news_enrich_enabled: bool = Field(default=True, alias="FINCOACH_NEWS_ENRICH_ENABLED")
    news_enrich_batch_size: int = Field(default=40, alias="FINCOACH_NEWS_ENRICH_BATCH_SIZE")
    # Per-feed HTTP timeout (seconds). Without this a single hung feed server can
    # block the whole poll cycle indefinitely.
    news_fetch_timeout: float = Field(default=10.0, alias="FINCOACH_NEWS_FETCH_TIMEOUT")
    # Articles older than this are pruned at the end of each poll.
    news_retention_days: int = Field(default=14, alias="FINCOACH_NEWS_RETENTION_DAYS")

    # Proactive news alerts — after each poll, freshly-collected articles are
    # matched against each user's watchlist (symbols/keywords) and a global
    # importance threshold; matches raise a NewsAlert the frontend surfaces in a
    # notification center + toast so the user can react ("take a position").
    news_alert_enabled: bool = Field(default=True, alias="FINCOACH_NEWS_ALERT_ENABLED")
    # |sentiment_score| at/above this raises an importance alert even with no
    # watchlist hit (a strongly bullish/bearish headline is worth surfacing).
    news_alert_score_threshold: float = Field(
        default=0.6, alias="FINCOACH_NEWS_ALERT_SCORE_THRESHOLD"
    )
    # Categories that always clear the importance threshold (market-moving).
    news_alert_categories: str = Field(
        default="regulation,ma,earnings", alias="FINCOACH_NEWS_ALERT_CATEGORIES"
    )

    @property
    def news_alert_category_set(self) -> set[str]:
        return {c.strip().lower() for c in self.news_alert_categories.split(",") if c.strip()}

    # Plan limits — free tier monthly chat-turn cap (cost control). Pro is
    # uncapped. 0 disables the gate entirely (treat everyone as unlimited).
    free_monthly_chat_turns: int = Field(
        default=15, alias="FINCOACH_FREE_MONTHLY_CHAT_TURNS"
    )

    # Billing — Pro plan price + iyzico credentials. When the iyzico keys are
    # unset the billing layer falls back to the in-process "mock" provider
    # (local dev / tests). Set all three to activate real iyzico checkout.
    pro_plan_price: float = Field(default=199.0, alias="FINCOACH_PRO_PLAN_PRICE")
    pro_plan_currency: str = Field(default="TRY", alias="FINCOACH_PRO_PLAN_CURRENCY")
    iyzico_api_key: str = Field(default="", alias="IYZICO_API_KEY")
    iyzico_secret_key: str = Field(default="", alias="IYZICO_SECRET_KEY")
    iyzico_base_url: str = Field(
        default="https://sandbox-api.iyzipay.com", alias="IYZICO_BASE_URL"
    )

    @property
    def iyzico_configured(self) -> bool:
        return bool(self.iyzico_api_key and self.iyzico_secret_key)

    # Auth
    jwt_secret: str = Field(default=DEFAULT_JWT_SECRET, alias="FINCOACH_JWT_SECRET")
    jwt_algorithm: str = "HS256"
    # 7 days: long enough that demo jurors/local sidecar users aren't re-prompted
    # constantly, short enough that a leaked token's blast-radius window is bounded
    # (Firebase ID tokens, the primary path in cloud, rotate ~hourly regardless).
    jwt_ttl_seconds: int = Field(default=60 * 60 * 24 * 7, alias="FINCOACH_JWT_TTL_SECONDS")  # 7 days
    # Brute-force / signup-spam guard on /auth/*. Enforced automatically on Cloud
    # Run; set this to force it on locally (off by default so dev/tests aren't
    # throttled). See app/auth/ratelimit.py.
    auth_rate_limit_force: bool = Field(default=False, alias="FINCOACH_AUTH_RATELIMIT_FORCE")

    # LLM
    # Locked to Gemini 3.1 Flash-Lite for cheapest multimodal inference ($0.25 / 1M input).
    # All roles (chat / vision / extract) use the same model.
    gemini_model: str = Field(default="gemini-3.1-flash-lite", alias="GEMINI_MODEL")
    gemini_vision_model: str = Field(
        default="gemini-3.1-flash-lite", alias="GEMINI_VISION_MODEL",
        description="Model for PDF/image vision dump.",
    )
    gemini_extract_model: str = Field(
        default="gemini-3.1-flash-lite", alias="GEMINI_EXTRACT_MODEL",
        description="Model for text-only schema extraction.",
    )
    gemini_temperature: float = Field(default=0.3, alias="GEMINI_TEMPERATURE")
    # Lower temperature for structured-output roles (router / advisor / risk
    # briefs) where determinism = correctness; prose roles use the default.
    gemini_structured_temperature: float = Field(
        default=0.0, alias="GEMINI_STRUCTURED_TEMPERATURE"
    )

    @property
    def vision_model(self) -> str:
        return self.gemini_vision_model or self.gemini_model

    @property
    def extract_model(self) -> str:
        return self.gemini_extract_model or self.gemini_model

    @property
    def news_feed_urls(self) -> list[str]:
        """Parsed, de-duplicated list of standing RSS feed URLs."""
        seen: set[str] = set()
        urls: list[str] = []
        for raw in self.news_feeds.split(","):
            url = raw.strip()
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
        return urls

    # LangSmith tracing
    langsmith_tracing: bool = Field(default=False, alias="LANGSMITH_TRACING")
    langsmith_project: str = Field(default="fincoach-hackathon", alias="LANGSMITH_PROJECT")

    @property
    def using_postgres(self) -> bool:
        return bool(self.database_url and self.database_url.startswith("postgresql"))

    @property
    def is_cloud_run(self) -> bool:
        """True when running on Cloud Run (K_SERVICE is injected by the runtime).

        The instance freezes when idle at min-instances=0, so an in-process
        interval scheduler can't be relied on — polling must be driven by an
        external trigger (Cloud Scheduler → POST /news/poll).
        """
        return bool(os.environ.get("K_SERVICE"))

    @property
    def db_url(self) -> str:
        if self.using_postgres:
            # SQLAlchemy needs psycopg2 driver prefix for sync engine
            url = self.database_url
            if url.startswith("postgresql://") and "+psycopg2" not in url:
                url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
            return url
        return f"sqlite:///{self.db_path}"

    @property
    def checkpointer_url(self) -> str:
        """URL for LangGraph AsyncPostgresSaver (psycopg3 format)."""
        if self.using_postgres:
            # psycopg3 expects plain postgresql:// (no driver prefix)
            url = self.database_url
            if "+psycopg2" in url:
                url = url.replace("+psycopg2", "")
            return url
        return self.db_path  # SQLite path for AsyncSqliteSaver


settings = Settings()


def configure_langsmith() -> None:
    """Wire LangSmith env vars so LangChain auto-traces when enabled."""
    if settings.langsmith_tracing and settings.langsmith_api_key:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
