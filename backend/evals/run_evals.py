"""Eval runner — drives the real chat graph over the golden QA set.

Usage (needs GEMINI_API_KEY for a real run):
    uv run python -m evals.run_evals                 # run all items
    uv run python -m evals.run_evals --category advisory --limit 5
    uv run python -m evals.run_evals --check         # offline: validate wiring, no LLM

Writes transcripts + deterministic checks to evals/results/run_<ts>.json, which
``grade.py`` then scores with the LLM-judge rubric.

The graph is driven exactly like the /chat endpoint: per turn we set the user/
currency/language contextvars and invoke the compiled supervisor with an
in-memory checkpointer so multi-turn (follow-up) items carry history.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

# Env MUST be set before importing app.* (settings read it at import).
_EVAL_DIR = Path(__file__).resolve().parent
os.environ.setdefault("FINCOACH_DB_PATH", str(_EVAL_DIR / "_eval.db"))
os.environ.setdefault("FINCOACH_NEWS_COLLECTOR_ENABLED", "false")

from evals.schema import QAItem, load_qa_set  # noqa: E402
from evals.seed import seed  # noqa: E402

RESULTS_DIR = _EVAL_DIR / "results"


def _normalize(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content if isinstance(p, dict)]
        return "".join(parts)
    return str(content or "")


def _extract(final_state: dict) -> dict:
    from langchain_core.messages import AIMessage

    msgs = final_state.get("messages") or []
    reply = ""
    for m in reversed(msgs):
        if isinstance(m, AIMessage):
            reply = _normalize(getattr(m, "content", "")).strip()
            break
    plan = final_state.get("plan") or {}
    findings = final_state.get("findings") or {}
    return {
        "reply": reply,
        "question_type": plan.get("question_type"),
        "requires_advisor": plan.get("requires_advisor"),
        "planned_specialists": plan.get("specialists") or [],
        "ran_specialists": sorted(findings.keys()),
        "suggestions": final_state.get("suggestions") or [],
    }


def _deterministic_checks(item: QAItem, res: dict) -> dict:
    reply_lc = (res["reply"] or "").lower()
    ran = set(res["ran_specialists"]) | set(res["planned_specialists"])
    exp = item.expects

    def _present(s: str) -> bool:  # "a|b" → any of a,b present
        return any(v.strip().lower() in reply_lc for v in s.split("|") if v.strip())

    checks = {
        "has_reply": bool(res["reply"]),
        "specialists_ok": set(exp.specialists).issubset(ran) if exp.specialists else None,
        "advisor_ok": (res["requires_advisor"] == exp.requires_advisor)
        if exp.requires_advisor is not None else None,
        "must_mention_ok": all(_present(s) for s in exp.must_mention) if exp.must_mention else None,
        "must_not_ok": (not any(s.lower() in reply_lc for s in exp.must_not))
        if exp.must_not else None,
    }
    failed = [k for k, v in checks.items() if v is False]
    checks["passed"] = not failed
    checks["failed"] = failed
    return checks


async def _run_item(graph, item: QAItem) -> dict:
    from langchain_core.messages import HumanMessage

    from app.auth import current_user_id_var, display_currency_var, ui_language_var

    current_user_id_var.set(1)
    display_currency_var.set(item.currency)
    ui_language_var.set(item.lang)

    config = {"configurable": {"thread_id": f"u1:eval-{item.id}"}}
    final: dict = {}
    t0 = time.monotonic()
    for msg in item.messages:
        final = await graph.ainvoke(
            {"messages": [HumanMessage(content=msg)], "user_id": 1}, config
        )
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    res = _extract(final)
    res["checks"] = _deterministic_checks(item, res)
    res["elapsed_ms"] = elapsed_ms
    return res


async def _run_all(items: list[QAItem]) -> list[dict]:
    from langgraph.checkpoint.memory import MemorySaver

    from app.agents.supervisor import build_supervisor

    graph = build_supervisor(checkpointer=MemorySaver())
    out: list[dict] = []
    for item in items:
        if item.expects.needs_document:
            out.append({"id": item.id, "skipped": "needs_document"})
            continue
        try:
            res = await _run_item(graph, item)
            res.update(id=item.id, category=item.category, lang=item.lang,
                       prompt=item.messages[-1])
            status = "PASS" if res["checks"]["passed"] else "CHECK-FAIL"
            print(f"  [{status}] {item.id}  ({res['elapsed_ms']}ms)")
        except Exception as exc:  # noqa: BLE001
            res = {"id": item.id, "error": f"{type(exc).__name__}: {exc}"}
            print(f"  [ERROR] {item.id}: {exc}")
        out.append(res)
    return out


def _offline_check(items: list[QAItem]) -> int:
    """Validate the whole harness WITHOUT calling the LLM."""
    print(f"✓ QA set: {len(items)} items loaded + schema-valid")
    cats: dict[str, int] = {}
    for it in items:
        cats[it.category] = cats.get(it.category, 0) + 1
    print("  by category:", json.dumps(cats, ensure_ascii=False))
    counts = seed()
    print(f"✓ seed OK: {counts}")
    from app.agents.supervisor import build_supervisor

    build_supervisor()
    print("✓ supervisor graph builds")
    print("\nHarness is wired. Set GEMINI_API_KEY and run without --check for a real run.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Run FinCoach chat evals over the golden QA set.")
    ap.add_argument("--check", action="store_true", help="Offline wiring check (no LLM).")
    ap.add_argument("--category", help="Only run one category.")
    ap.add_argument("--limit", type=int, help="Cap number of items.")
    ap.add_argument("--qa", type=Path, help="Path to a JSONL QA set.")
    args = ap.parse_args()

    items = load_qa_set(args.qa)
    if args.category:
        items = [i for i in items if i.category == args.category]
    if args.limit:
        items = items[: args.limit]

    if args.check:
        return _offline_check(items)

    print(f"Seeding demo investor + running {len(items)} items…")
    seed()
    results = asyncio.run(_run_all(items))

    RESULTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"run_{ts}.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    ran = [r for r in results if "checks" in r]
    passed = sum(1 for r in ran if r["checks"]["passed"])
    print(f"\nDeterministic checks: {passed}/{len(ran)} passed")
    print(f"Wrote {out_path.relative_to(_EVAL_DIR.parent)}  → now: uv run python -m evals.grade {out_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
