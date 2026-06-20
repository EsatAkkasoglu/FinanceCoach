# FinCoach chat evals

A golden-QA-set harness to answer *"does the AI actually work / is it usable for
our customer?"* — and to drive prompt improvements with a measurable feedback
loop instead of guessing.

## What's here

| File | Role |
|---|---|
| `qa_sets/chat_qa.jsonl` | ~40 realistic Turkish/English customer questions + per-item `expects` (which desks should run, advisor on/off, must/​must-not strings) and a `rubric` note for the judge. Covers portfolio, funds/TEFAS, crypto, budget, goals, advisory, news, out-of-scope, **regulatory safety**, ambiguity, **prompt-injection**, and follow-ups. |
| `seed.py` | Seeds a representative Turkish retail investor (user_id=1) so the agents have real data. Deterministic + idempotent. |
| `run_evals.py` | Drives the **real chat graph** over the set exactly like `/chat`, records transcripts + deterministic checks. |
| `rubric.py` | The grading rubric (8 dimensions, nominal 0/0.5/1 scoring) + the LLM-judge prompt with bias controls. |
| `grade.py` | Scores a run with the LLM-judge, writes per-item scores + an aggregate report. |

## Run it

```bash
cd backend

# 1) Offline wiring check — no API key needed (validates QA set, seed, graph build)
uv run python -m evals.run_evals --check

# 2) Real run — needs GEMINI_API_KEY in backend/.env
uv run python -m evals.run_evals                      # all items
uv run python -m evals.run_evals --category advisory  # one slice
# → writes evals/results/run_<ts>.json

# 3) Grade the run with the LLM-judge
uv run python -m evals.grade run_<ts>.json
# → writes results/<run>.graded.json + <run>.report.md (dimension averages,
#   pass rate, weakest-10 replies with concrete suggested fixes)
```

## The improvement loop

1. Run + grade → read `report.md` (which dimensions/items are weakest).
2. Fix the responsible agent **prompt** (e.g. usability, language, safety).
3. Re-run the same set → confirm the score moved up, nothing regressed.
4. Add any production question that embarrassed the coach as a new golden item.

Deterministic checks (routing, must/​must-not, advisor on/off) catch hard
regressions even without the judge; the judge scores the soft usability/tone/
safety dimensions a regex can't.

## Notes

- `_eval.db` (a throwaway SQLite file) and `results/` are git-ignored.
- `needs_document` items are skipped unless an uploaded doc is indexed.
- The judge is itself an LLM — treat scores as a smoke-test signal, and spot-read
  the actual replies in the run JSON, not just the numbers.
