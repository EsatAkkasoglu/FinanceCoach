"""Eval QA-set schema + loader.

A golden QA item is one realistic user message (or a multi-turn list) plus an
``expects`` block describing what a *good* answer looks like — used both for
deterministic checks (which desks ran, advisor on/off, must/​must-not strings,
language) and as context for the LLM-judge rubric grader.

Kept dependency-light (pydantic v2, already a project dep) so the set can be
validated offline without a Gemini key.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

EVALS_DIR = Path(__file__).resolve().parent
QA_DIR = EVALS_DIR / "qa_sets"

Category = Literal[
    "portfolio", "funds", "crypto", "market", "budget", "goals",
    "advisory", "news", "documents", "out_of_scope", "regulatory",
    "ambiguous", "adversarial", "followup",
]


class Expects(BaseModel):
    """What a good answer should/shouldn't do for this item."""
    specialists: list[str] = Field(
        default_factory=list,
        description="Desks that SHOULD run (subset check — extras allowed unless strict).",
    )
    requires_advisor: bool | None = Field(
        default=None, description="Expected advisor on/off; None = don't check."
    )
    must_mention: list[str] = Field(
        default_factory=list,
        description="Case-insensitive substrings the reply SHOULD contain (any-of per string).",
    )
    must_not: list[str] = Field(
        default_factory=list,
        description="Case-insensitive substrings the reply MUST NOT contain.",
    )
    needs_document: bool = Field(
        default=False, description="Requires an uploaded doc; skipped unless --with-docs.",
    )
    rubric: str = Field(
        default="",
        description="Plain-language note to the judge: what a great answer looks like.",
    )


class QAItem(BaseModel):
    id: str
    category: Category
    lang: Literal["tr", "en"] = "tr"
    currency: Literal["TRY", "USD", "EUR"] = "TRY"
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    prompt: str | None = Field(default=None, description="Single-turn user message.")
    turns: list[str] | None = Field(default=None, description="Multi-turn messages (same thread).")
    expects: Expects = Field(default_factory=Expects)

    @model_validator(mode="after")
    def _one_of_prompt_or_turns(self) -> QAItem:
        if not self.prompt and not self.turns:
            raise ValueError(f"item {self.id}: needs either 'prompt' or 'turns'")
        if self.prompt and self.turns:
            raise ValueError(f"item {self.id}: set 'prompt' OR 'turns', not both")
        return self

    @property
    def messages(self) -> list[str]:
        return self.turns if self.turns else [self.prompt or ""]


def load_qa_set(path: Path | None = None) -> list[QAItem]:
    """Load + validate a JSONL golden set. Raises on the first malformed line."""
    path = path or (QA_DIR / "chat_qa.jsonl")
    items: list[QAItem] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw or raw.startswith("//"):
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}:{lineno} invalid JSON: {exc}") from exc
            item = QAItem.model_validate(data)
            if item.id in seen:
                raise ValueError(f"{path.name}:{lineno} duplicate id '{item.id}'")
            seen.add(item.id)
            items.append(item)
    return items
