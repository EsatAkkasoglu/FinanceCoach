"""LLM factories."""
from __future__ import annotations

from functools import lru_cache

from langchain_google_genai import ChatGoogleGenerativeAI

from app.settings import settings


def _require_key() -> str:
    if not settings.gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Copy backend/.env.example to backend/.env and fill it in."
        )
    return settings.gemini_api_key


@lru_cache(maxsize=1)
def get_llm() -> ChatGoogleGenerativeAI:
    """Application chat model."""
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        temperature=settings.gemini_temperature,
        google_api_key=_require_key(),
    )
