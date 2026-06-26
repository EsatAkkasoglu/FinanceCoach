"""Database models. Single-user prototype, so a single User row drives everything.

Schema:
    user — profile, risk score, settings
    holding — current portfolio positions (ticker, qty, cost basis)
    transaction — income/expense rows (categorized)
    goal — savings/financial targets
    chat_message — conversation history (used by Memory agent / RAG)
    document — uploaded statements / receipts (provenance for Document Parser)
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class RiskProfile(str, Enum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class AssetClass(str, Enum):
    STOCK = "stock"
    CRYPTO = "crypto"
    CASH = "cash"
    BOND = "bond"
    ETF = "etf"
    FUND = "fund"


class TransactionType(str, Enum):
    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"


class AccountKind(str, Enum):
    CASH = "cash"
    CHECKING = "checking"
    SAVINGS = "savings"
    CREDIT_CARD = "credit_card"


class SubscriptionCycle(str, Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class TransactionSource(str, Enum):
    MANUAL = "manual"
    UPLOAD = "upload"
    CHAT = "chat"
    SUBSCRIPTION = "subscription"


class User(Base):
    __tablename__ = "user"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)
    firebase_uid = Column(String(128), unique=True, nullable=True, index=True)
    name = Column(String(120), nullable=False, default="")
    avatar = Column(String(64), default="default")
    monthly_income = Column(Float, default=0.0)
    risk_score = Column(Integer, default=50)              # 0-125
    risk_profile = Column(String(32), default=RiskProfile.BALANCED.value)
    roast_mode = Column(Integer, default=0)               # 0/1 bool flag
    tier = Column(String(16), nullable=False, default="free")  # "free" | "pro"
    created_at = Column(DateTime, default=datetime.utcnow)

    holdings = relationship("Holding", back_populates="user", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")
    goals = relationship("Goal", back_populates="user", cascade="all, delete-orphan")
    messages = relationship("ChatMessage", back_populates="user", cascade="all, delete-orphan")


class Holding(Base):
    __tablename__ = "holding"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    ticker = Column(String(32), nullable=False)
    asset_class = Column(String(16), default=AssetClass.STOCK.value)
    quantity = Column(Float, nullable=False)
    cost_basis = Column(Float, nullable=False)            # avg per-unit cost
    currency = Column(String(8), nullable=False, default="USD")  # currency of cost_basis / quote
    acquired_at = Column(Date, default=datetime.utcnow)

    user = relationship("User", back_populates="holdings")


class Account(Base):
    """A place money lives — bank account, cash wallet, credit card."""

    __tablename__ = "account"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    name = Column(String(120), nullable=False)
    kind = Column(String(32), default=AccountKind.CHECKING.value)
    balance = Column(Float, default=0.0)
    currency = Column(String(8), default="TRY")
    institution = Column(String(120), nullable=True)
    color = Column(String(16), default="emerald")
    archived = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", backref="accounts")


class Subscription(Base):
    """A recurring payment OR income source the user wants to track."""

    __tablename__ = "subscription"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    name = Column(String(120), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(8), default="TRY")
    cycle = Column(String(16), default=SubscriptionCycle.MONTHLY.value)
    direction = Column(String(8), default="expense")  # 'income' | 'expense'
    next_charge_on = Column(Date, nullable=True)
    category = Column(String(64), default="subscriptions")
    icon = Column(String(32), nullable=True)
    account_id = Column(Integer, ForeignKey("account.id"), nullable=True)
    active = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", backref="subscriptions")
    account = relationship("Account")


class Transaction(Base):
    __tablename__ = "transaction"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    occurred_on = Column(Date, nullable=False)
    type = Column(String(16), default=TransactionType.EXPENSE.value)
    amount = Column(Float, nullable=False)
    currency = Column(String(8), default="TRY")
    category = Column(String(64), default="uncategorized")
    description = Column(Text, default="")
    source = Column(String(16), default=TransactionSource.MANUAL.value)
    document_id = Column(Integer, ForeignKey("document.id"), nullable=True)
    account_id = Column(Integer, ForeignKey("account.id"), nullable=True)
    subscription_id = Column(Integer, ForeignKey("subscription.id"), nullable=True)

    user = relationship("User", back_populates="transactions")
    document = relationship("Document")
    account = relationship("Account")
    subscription = relationship("Subscription")


class Goal(Base):
    __tablename__ = "goal"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    title = Column(String(120), nullable=False)            # e.g. "Home down payment"
    target_amount = Column(Float, nullable=False)
    target_date = Column(Date, nullable=True)
    current_amount = Column(Float, default=0.0)
    icon = Column(String(32), default="target")
    currency = Column(String(8), default="TRY")

    user = relationship("User", back_populates="goals")


class ChatMessage(Base):
    __tablename__ = "chat_message"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    role = Column(String(16), nullable=False)             # "user" | "assistant"
    content = Column(Text, nullable=False)
    agent = Column(String(32), nullable=True)             # which agent produced it
    citations = Column(Text, nullable=True)               # JSON-encoded sources
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="messages")


class Conversation(Base):
    __tablename__ = "conversation"

    id = Column(String(36), primary_key=True)          # UUID
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    thread_id = Column(String(36), nullable=False, unique=True)  # LangGraph thread_id
    title = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    archived = Column(Integer, default=0)              # 0/1 bool

    user = relationship("User", backref="conversations")


class Document(Base):
    __tablename__ = "document"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    kind = Column(String(32), default="bank_statement")   # bank_statement | receipt | other
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    parsed_count = Column(Integer, default=0)


class NetWorthSnapshot(Base):
    """Daily net-worth snapshot for sparkline / trend charts.

    Captured once per day per user. ``value`` is the converted total in
    ``currency`` (typically USD or the user's display currency at write-time).
    Two rows on the same date for the same user are unique-conflicted; the
    writer upserts so manual refreshes don't pollute the timeline.
    """

    __tablename__ = "net_worth_snapshot"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False, index=True)
    captured_on = Column(Date, nullable=False, index=True)
    value = Column(Float, nullable=False)
    currency = Column(String(8), nullable=False, default="USD")
    created_at = Column(DateTime, default=datetime.utcnow)


class MessageFeedback(Base):
    """User rating + optional reason on a specific assistant message.

    Identifies a message by ``(thread_id, message_id)`` where ``message_id``
    is the per-conversation client-side ID (e.g. ``a-1733058321``). One row
    per (user, message_id); subsequent posts overwrite the rating + reason.
    Used to mine the strategist for routing examples and to bias the memory
    retriever toward positively-rated turns.
    """

    __tablename__ = "message_feedback"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    thread_id = Column(String(64), nullable=False, index=True)
    message_id = Column(String(64), nullable=False, index=True)
    rating = Column(String(8), nullable=False)              # "up" | "down"
    reason = Column(Text, nullable=True)
    agent = Column(String(32), nullable=True)
    excerpt = Column(Text, nullable=True)                   # first 400 chars of the rated reply
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class NewsArticle(Base):
    """A headline collected by the background news poller.

    Written by ``services.news_collector`` (out of the request path) and read
    by ``tools.news_tools.search_news`` (DB-first) and ``GET /news/feed``.
    Enrichment (sentiment / category / summary) is filled in the same poll.

    Dedup keys, cheapest → strongest:
      • ``canonical_url`` — UTM-stripped URL, UNIQUE; collapses re-syndication.
      • ``content_hash``  — normalized-title SHA1; collapses same-title reposts
        with different URLs (and is the hook point for embedding dedup later).
    """

    __tablename__ = "news_article"

    id = Column(Integer, primary_key=True)
    canonical_url = Column(String(1024), unique=True, nullable=False, index=True)
    url = Column(String(1024), nullable=False)
    title = Column(String(512), nullable=False)
    source = Column(String(128), nullable=False, default="")
    published_at = Column(DateTime, nullable=True, index=True)
    snippet = Column(Text, nullable=True)
    lang = Column(String(8), nullable=False, default="en")
    tickers = Column(String(256), nullable=True)            # "ASELS.IS,THYAO.IS"
    category = Column(String(64), nullable=True, index=True)
    sentiment = Column(String(16), nullable=True)           # positive | neutral | negative
    sentiment_score = Column(Float, nullable=True)          # -1..1
    summary = Column(Text, nullable=True)                   # 1-line enrichment summary
    content_hash = Column(String(64), nullable=False, default="", index=True)
    enriched = Column(Integer, nullable=False, default=0)   # 0/1 — has sentiment/category been set
    fetched_at = Column(DateTime, default=datetime.utcnow, index=True)


class FeedState(Base):
    """Per-feed conditional-GET state so unchanged feeds return 304 (≈0 bytes).

    feedparser supports ``etag`` / ``modified`` natively; we persist them here
    between poll cycles.
    """

    __tablename__ = "feed_state"

    url = Column(String(1024), primary_key=True)
    etag = Column(String(512), nullable=True)
    last_modified = Column(String(256), nullable=True)
    last_polled_at = Column(DateTime, nullable=True)
    last_status = Column(Integer, nullable=True)            # last HTTP status (200/304/…)
    error_count = Column(Integer, nullable=False, default=0)


class WatchKind(str, Enum):
    SYMBOL = "symbol"      # a ticker/fund code — matched against NewsArticle.tickers
    KEYWORD = "keyword"    # a free-text theme — matched against title + snippet


class Watchlist(Base):
    """A symbol or keyword the user wants proactive news alerts for.

    Drives ``services.news_alerts.generate_alerts``: a freshly-collected article
    raises a ``NewsAlert`` when it matches a watchlist row (or clears the global
    importance threshold). Single-user prototype, so rows are scoped to user_id=1.
    """

    __tablename__ = "watchlist"
    __table_args__ = (UniqueConstraint("user_id", "kind", "value", name="uq_watchlist_user_kind_value"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False, index=True)
    kind = Column(String(16), nullable=False, default=WatchKind.SYMBOL.value)
    # Normalized at write time: symbols upper-cased, keywords lower-cased.
    value = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class NewsAlert(Base):
    """A per-user proactive alert: 'this fresh headline is relevant to you'.

    Written by the collector (out of the request path) when a new article matches
    the user's watchlist or clears the importance threshold; read by the frontend
    notification center via ``GET /news/alerts``. One alert per (user, article).
    """

    __tablename__ = "news_alert"
    __table_args__ = (UniqueConstraint("user_id", "article_id", name="uq_news_alert_user_article"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False, index=True)
    article_id = Column(
        Integer, ForeignKey("news_article.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Why this fired: "watchlist:AAPL" | "category:regulation" | "sentiment".
    reason = Column(String(64), nullable=False)
    priority = Column(Integer, nullable=False, default=1)   # 2 = watchlist hit, 1 = importance
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    read_at = Column(DateTime, nullable=True)               # NULL = unread

    article = relationship("NewsArticle")


class Waitlist(Base):
    """Landing-page early-access signups — Phase 0 demand validation.

    Public (no auth): the marketing landing posts here when a visitor asks for
    early access to a paid tier. One row per email; ``tier`` captures which plan
    they wanted (the willingness-to-pay signal), ``source`` where they signed up.
    """

    __tablename__ = "waitlist"

    id = Column(Integer, primary_key=True)
    email = Column(String(254), unique=True, nullable=False, index=True)
    tier = Column(String(32), nullable=True)        # "pro" | "team" | None
    source = Column(String(64), nullable=True)      # "pricing" | "cta" | …
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class UsageCounter(Base):
    """Per-user monthly metered-action counter (chat turns) for plan limits.

    One row per ``(user_id, period)`` where ``period`` is the UTC calendar
    month ``"YYYY-MM"``. The chat endpoint increments ``chat_turns`` on each
    accepted turn; free-tier users are gated when they exceed the configured
    monthly cap. Pro users are never gated (no row pressure either way).
    """

    __tablename__ = "usage_counter"
    __table_args__ = (
        UniqueConstraint("user_id", "period", name="uq_usage_user_period"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False, index=True)
    period = Column(String(7), nullable=False, index=True)   # "YYYY-MM" (UTC)
    chat_turns = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
