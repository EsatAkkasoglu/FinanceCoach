"""Defang indirect prompt-injection in untrusted retrieved content.

Text pulled from news feeds, uploaded PDFs/images, or other external sources is
*data*, never instructions — but it rides into the specialist agents' context as
tool output, the classic indirect-injection channel (OWASP LLM01). The robust
mitigation is the system-prompt guard each consuming agent carries; this module
is the defense-in-depth layer underneath it.

``defang_untrusted`` only neutralizes a tight set of high-signal, multi-word
control phrases ("ignore previous instructions", "you are now …", a literal
``system:`` role marker, etc.). It deliberately does NOT scrub generic finance
prose, so a real statement like "disregard the earlier price target" passes
through untouched. Matches are wrapped in a visible ``⟦flagged⟧`` marker rather
than deleted, so the model sees the attempt was caught instead of silently
losing surrounding context.
"""
from __future__ import annotations

import re

# Multi-word, instruction-shaped patterns that essentially never occur verbatim
# in legitimate headlines or financial documents but are the staple of injection
# payloads. Kept tight on purpose — over-matching would corrupt real content.
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:ignore|disregard|forget)\b[^.\n]{0,40}\b(?:previous|prior|above|earlier|all)\b[^.\n]{0,20}\b(?:instruction|instructions|prompt|prompts|context|rules?)\b", re.IGNORECASE),
    re.compile(r"\byou\s+are\s+now\b[^.\n]{0,60}", re.IGNORECASE),
    re.compile(r"\b(?:new|updated|real|actual)\s+(?:instruction|instructions|system\s+prompt)\b", re.IGNORECASE),
    re.compile(r"(?m)^\s*(?:system|assistant|developer)\s*:", re.IGNORECASE),
    re.compile(r"</?(?:system|instructions?|prompt)>", re.IGNORECASE),
    re.compile(r"\bdo\s+not\s+(?:follow|obey|tell|reveal)\b[^.\n]{0,40}", re.IGNORECASE),
    re.compile(r"\b(?:reveal|print|repeat|show)\b[^.\n]{0,30}\b(?:system\s+prompt|your\s+instructions|api[\s_-]?key)\b", re.IGNORECASE),
]

# Cap on a single untrusted blob fed to the model — a defense against a giant
# chunk crowding out the real prompt (LLM10 / context stuffing).
_MAX_LEN = 4000


def defang_untrusted(text: str | None, *, max_len: int = _MAX_LEN) -> str:
    """Neutralize obvious injection control-phrases in untrusted text.

    Returns the text with any flagged span wrapped in ``⟦flagged: …⟧`` and
    truncated to ``max_len``. ``None``/empty input returns an empty string.
    """
    if not text:
        return ""
    out = text
    for pattern in _INJECTION_PATTERNS:
        out = pattern.sub(lambda m: f"⟦flagged: {m.group(0)}⟧", out)
    if len(out) > max_len:
        out = out[:max_len] + " …[truncated]"
    return out
