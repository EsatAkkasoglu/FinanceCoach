"""LLM factories + token-usage logging."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_google_genai import ChatGoogleGenerativeAI

from app.settings import settings

logger = logging.getLogger("fincoach.tokens")

# Gemini 3.1 Flash-Lite pricing (USD per 1M tokens, standard tier)
_INPUT_COST_PER_M  = 0.25
_OUTPUT_COST_PER_M = 1.50


def _read_token_usage(response: Any) -> tuple[int, int]:
    """Extract (input_tokens, output_tokens) from a LangChain ``LLMResult``.

    Different ``langchain-google-genai`` versions stash usage in different
    places. We probe every known location in priority order:

      1. ``response.llm_output["token_usage"]``      (older path)
      2. ``response.llm_output["usage_metadata"]``   (intermediate path)
      3. ``response.generations[*][*].message.usage_metadata``  (current path —
         AIMessage.usage_metadata standardized by LangChain)
      4. ``response.generations[*][*].generation_info["usage_metadata"]``
         (streaming / Gemini-specific path)

    Returns (0, 0) if nothing is found — never raises.
    """
    inp = 0
    out = 0

    llm_output = getattr(response, "llm_output", None) or {}
    if isinstance(llm_output, dict):
        for key in ("token_usage", "usage_metadata"):
            usage = llm_output.get(key) or {}
            if isinstance(usage, dict):
                inp = inp or usage.get("input_tokens") or usage.get("prompt_token_count") or 0
                out = out or usage.get("output_tokens") or usage.get("candidates_token_count") or 0

    if inp or out:
        return int(inp), int(out)

    # Walk per-generation usage. Streaming responses always populate this.
    for gen_list in getattr(response, "generations", None) or []:
        for gen in gen_list or []:
            msg = getattr(gen, "message", None)
            usage = getattr(msg, "usage_metadata", None) if msg is not None else None
            if not isinstance(usage, dict):
                info = getattr(gen, "generation_info", None) or {}
                usage = info.get("usage_metadata") if isinstance(info, dict) else None
            if isinstance(usage, dict):
                inp += int(usage.get("input_tokens") or usage.get("prompt_token_count") or 0)
                out += int(usage.get("output_tokens") or usage.get("candidates_token_count") or 0)

    return inp, out


class TokenLogger(BaseCallbackHandler):
    """Logs token counts and estimated cost after every LLM call."""

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        try:
            inp, out = _read_token_usage(response)
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


@lru_cache(maxsize=8)
def get_llm(temperature: float | None = None) -> ChatGoogleGenerativeAI:
    """Application chat model with token-usage logging.

    ``temperature=None`` uses the configured default
    (``settings.gemini_temperature``, ~0.3) — right for prose (the
    synthesizer). Pass an explicit low value for roles where determinism is
    correctness: structured routing (the strategist's ``ExecutionPlan``) and
    structured briefs (advisor / risk_profiler) should run near 0.0 so the
    same question yields the same plan. Instances are cached per temperature.
    """
    temp = settings.gemini_temperature if temperature is None else temperature
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        temperature=temp,
        google_api_key=_require_key(),
        callbacks=[TokenLogger()],
        max_output_tokens=8192,   # Gemini Flash-Lite cap; prevents truncated research replies
    )
