"""Grade a run with the LLM-as-judge rubric.

Usage (needs GEMINI_API_KEY):
    uv run python -m evals.grade run_<ts>.json

Reads evals/results/<run>.json (from run_evals.py), scores each reply against
the rubric in rubric.py, and writes:
  • results/<run>.graded.json   — per-item dimension scores + critique + fix
  • results/<run>.report.md     — aggregate scores, pass rate, worst items
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

_EVAL_DIR = Path(__file__).resolve().parent
os.environ.setdefault("FINCOACH_DB_PATH", str(_EVAL_DIR / "_eval.db"))
os.environ.setdefault("FINCOACH_NEWS_COLLECTOR_ENABLED", "false")

from evals.rubric import (  # noqa: E402
    DIMENSIONS,
    JUDGE_SYSTEM,
    JudgeVerdict,
    build_judge_prompt,
)
from evals.schema import load_qa_set  # noqa: E402

RESULTS_DIR = _EVAL_DIR / "results"


def _judge(llm, item, res) -> dict:
    from langchain_core.messages import HumanMessage, SystemMessage

    prompt = build_judge_prompt(
        item_id=item.id, lang=item.lang, category=item.category,
        user_messages=item.messages, reply=res.get("reply", ""),
        expected_rubric=item.expects.rubric,
        ran_specialists=res.get("ran_specialists", []),
        requires_advisor=res.get("requires_advisor"),
    )
    verdict: JudgeVerdict = llm.invoke(
        [SystemMessage(content=JUDGE_SYSTEM), HumanMessage(content=prompt)]
    )
    scores = {s.dimension: s.score for s in verdict.scores}
    return {
        "id": item.id, "category": item.category, "lang": item.lang,
        "scores": scores, "passed": verdict.passed,
        "critique": verdict.critique, "suggested_fix": verdict.suggested_fix,
        "deterministic": res.get("checks", {}),
    }


def _report(graded: list[dict]) -> str:
    judged = [g for g in graded if "scores" in g]
    if not judged:
        return "# Eval report\n\nNo judged items.\n"
    dim_tot: dict[str, float] = defaultdict(float)
    dim_n: dict[str, int] = defaultdict(int)
    for g in judged:
        for dim, sc in g["scores"].items():
            dim_tot[dim] += sc
            dim_n[dim] += 1
    passed = sum(1 for g in judged if g["passed"])

    lines = ["# Eval report\n", f"Items judged: **{len(judged)}** · "
             f"passed (intent+grounding+safety): **{passed}/{len(judged)}**\n",
             "## Dimension averages (1.0 = best)\n", "| Dimension | Avg |", "|---|---|"]
    for dim in DIMENSIONS:
        if dim_n[dim]:
            lines.append(f"| {dim} | {dim_tot[dim]/dim_n[dim]:.2f} |")

    worst = sorted(judged, key=lambda g: sum(g["scores"].values()) / max(1, len(g["scores"])))[:10]
    lines += ["\n## Weakest 10 replies (fix these first)\n"]
    for g in worst:
        avg = sum(g["scores"].values()) / max(1, len(g["scores"]))
        lines.append(f"- **{g['id']}** ({g['category']}, avg {avg:.2f}) — {g['critique']} "
                     f"_→ fix:_ {g['suggested_fix']}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="LLM-judge grade an eval run.")
    ap.add_argument("run", help="Run JSON filename under evals/results/ (or a path).")
    ap.add_argument("--qa", type=Path, help="QA set used (to read per-item rubrics).")
    args = ap.parse_args()

    run_path = Path(args.run)
    if not run_path.exists():
        run_path = RESULTS_DIR / args.run
    results = json.loads(run_path.read_text(encoding="utf-8"))
    items = {i.id: i for i in load_qa_set(args.qa)}

    from app.agents.llm import get_llm

    llm = get_llm(0.0).with_structured_output(JudgeVerdict)

    graded: list[dict] = []
    for res in results:
        item = items.get(res.get("id"))
        if item is None or "reply" not in res:
            continue
        try:
            graded.append(_judge(llm, item, res))
            print(f"  judged {res['id']}: {'PASS' if graded[-1]['passed'] else 'FAIL'}")
        except Exception as exc:  # noqa: BLE001
            print(f"  judge error {res.get('id')}: {exc}")

    stem = run_path.stem
    (RESULTS_DIR / f"{stem}.graded.json").write_text(
        json.dumps(graded, ensure_ascii=False, indent=2), encoding="utf-8")
    report = _report(graded)
    (RESULTS_DIR / f"{stem}.report.md").write_text(report, encoding="utf-8")
    print("\n" + report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
