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
    Column, Date, DateTime, Float, ForeignKey, Integer, String, Text,
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
    password_hash = Column(String(255), nullable=False)
    name = Column(String(120), nullable=False, default="")
    avatar = Column(String(64), default="default")
    monthly_income = Column(Float, default=0.0)
    risk_score = Column(Integer, default=50)              # 0-125
    risk_profile = Column(String(32), default=RiskProfile.BALANCED.value)
    roast_mode = Column(Integer, default=0)               # 0/1 bool flag
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
