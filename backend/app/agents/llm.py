"""LLM factories + token-usage logging."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_google_genai import ChatGoogleGenerativeAI

from app.settings import settings

logger = logging.getLogger("fincoach.tokens")

# Gemini 3.1 Flash-Lite Preview pricing (USD per 1M tokens, standard tier)
_INPUT_COST_PER_M  = 0.25
_OUTPUT_COST_PER_M = 1.50


class TokenLogger(BaseCallbackHandler):
    """Logs token counts and estimated cost after every LLM call."""

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        try:
            usage = response.llm_output.get("usage_metadata") or {}
            # Gemini SDK exposes prompt_token_count / candidates_token_count
            inp  = usage.get("prompt_token_count") or usage.get("input_tokens") or 0
            out  = usage.get("candidates_token_count") or usage.get("output_tokens") or 0
            if inp == 0 and out == 0:
                # fallback: iterate generations
                for gen_list in response.generations:
                    for gen in gen_list:
                        meta = getattr(gen, "generation_info", {}) or {}
                        u = meta.get("usage_metadata") or {}
                        inp += u.get("prompt_token_count", 0)
                        out += u.get("candidates_token_count", 0)
            cost = (inp * _INPUT_COST_PER_M + out * _OUTPUT_COST_PER_M) / 1_000_000
            logger.info(
                "token_usage | model=%s | input=%d | output=%d | total=%d | cost=$%.6f",
                settings.gemini_model, inp, out, inp + out, cost,
            )
        except Exception:  # noqa: BLE001
            pass  # never crash on logging


def _require_key() -> str:
    if not settings.gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Copy backend/.env.example to backend/.env and fill it in."
        )
    return settings.gemini_api_key


@lru_cache(maxsize=1)
def get_llm() -> ChatGoogleGenerativeAI:
    """Application chat model with token-usage logging."""
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        temperature=settings.gemini_temperature,
        google_api_key=_require_key(),
        callbacks=[TokenLogger()],
    )
