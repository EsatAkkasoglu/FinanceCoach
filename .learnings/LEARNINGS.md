# Learnings

## [LRN-20260518-001] correction

**Logged**: 2026-05-18T12:40:00Z
**Priority**: high
**Status**: resolved
**Area**: backend

### Summary
Chat agents had no visibility into the user's Goals table — synthesizer asked the user for target amount / date even when the goal was already in the DB.

### Details
The `Goal` model existed and was exposed via `/goals` CRUD endpoints, but:
- No `@tool` wrapped goal reads, so agents (advisor, budget_coach, etc.) could never call them.
- `synthesizer._format_user_context` injected risk_profile, monthly_income, and holdings into every reply but **omitted goals**.
- The strategist router prompt and keyword-fallback had no goal-related keywords (hedef, biriktir, peşinat, on track, emergency fund), so goal questions weren't even routed to a goal-aware desk.
- Result: when user asked "ev hedefime ulaşmak için aylık ne biriktirmeliyim?", the LLM had no choice but to template a generic allocation table and ask back for amount + vade — even though both were already in `goal` rows.

### Suggested Action (applied)
1. New `backend/app/tools/goal_tools.py` with `list_user_goals` and `update_goal_progress` `@tool` wrappers. `list_user_goals` returns each goal with progress_pct, days_left, months_left, monthly_savings_needed, plus a summary aggregate.
2. Wired both tools into `budget_coach` agent (single owner of "am I on track" questions); updated its `_TOOLS` and prompt to require `list_user_goals` whenever goals are in scope, and forbid asking the user for values already in the tool output.
3. Extended `synthesizer._format_user_context` to append a compact `goals=[title cur/target (pct%) need~X/mo for Yd]` line so even when budget_coach isn't dispatched, the synthesizer has the data inline.
4. Added a `GOALS RULE` block to `SYNTHESIZER_PROMPT` forbidding "what's your target amount?" style questions when a matching goal is in USER PROFILE, and a `Goals (READ + WRITE)` capability section to the CAPABILITY MAP for suggestion-picking.
5. Strategist router: documented `budget_coach` as the goal-question owner, added a goal-routing example, and expanded the keyword fallback with hedef / biriktir / peşinat / acil fon / on track / emergency fund.

### Metadata
- Source: user_feedback (screenshot of synthesizer asking "Hedeflediğiniz evin yaklaşık değeri nedir?" while user already had "Ev peşinatı 410.000/1.500.000" goal saved)
- Related Files:
  - `backend/app/tools/goal_tools.py` (new)
  - `backend/app/agents/budget_coach.py`
  - `backend/app/agents/synthesizer.py`
  - `backend/app/agents/supervisor.py`
- Tags: agents, prompt-engineering, tool-binding, personalization

### Resolution
- **Resolved**: 2026-05-18T12:40:00Z
- **Notes**: Backend hot-reloaded successfully. End-to-end test recommended: ask "ev hedefim için aylık ne biriktirmeliyim?" with a goal seeded — expected to quote 410.000 / 1.500.000 and compute monthly_savings_needed from days_left rather than asking for input.

---

## [LRN-20260518-002] best_practice

**Logged**: 2026-05-18T12:50:00Z
**Priority**: high
**Status**: resolved
**Area**: backend

### Summary
Synthesizer + strategist were producing structurally identical "Önerilen Stratejik Dağılım + Neden bu öneri?" replies on every advisory turn, regardless of whether the user actually asked for an allocation plan. Felt canned.

### Details
Two coupled problems with the prompts:

1. **Strategist defaulted advisory ON for too many questions.** The prompt said "For advisory questions, default to a genuinely holistic answer …" with the full 5-desk lineup. State-style goal questions ("yolda mıyım", "şuanki tempoda yeter mi", "aylık ne biriktirmeliyim") were getting `requires_advisor=True`, which fired the Investment Committee unnecessarily.

2. **Synthesizer's advisory mode REQUIRED an allocation table.** The prompt literally said "Required structure: Start with verdict… Include a compact markdown allocation/action table… Why this recommendation? section…". Once `requires_advisor=True` and `advisor_brief` existed, the template was mandatory. Hence every reply looked like a clone.

Tried fixing with keyword lists first — user correctly pushed back that keywords are brittle and the prompts themselves were the problem.

### Suggested Action (applied)
Rewrote both prompts around two principles, not keyword lists:

**Synthesizer** (`SYNTHESIZER_PROMPT`):
- Replaced the rigid "REPLY MODE RULES" with a "HOW TO SHAPE THE REPLY — PRINCIPLE, NOT TEMPLATE" section centered on: *the SHAPE of the reply must match the SHAPE of the question*.
- Added an explicit **ANTI-TEMPLATE** block listing the canned patterns to avoid (allocation table grafted onto verification questions, recurring Risk/Security/Growth triplet, boilerplate openings, generic closers).
- Introduced a **speech-act classifier** the synthesizer applies to the current message: verification / quantification / fact / data-rich / plan-request / explain / follow-up / mixed → and a short paragraph each for what good output looks like for that act.
- Added a **VARIETY HEURISTIC**: glance at the last 1-2 assistant replies in RECENT CONVERSATION; if the draft repeats headings/openings, rewrite. Two consecutive replies should not look like clones.
- Updated the runtime payload nudge to say `advisor_brief` is INPUT, not OUTPUT — render only the parts that answer THIS question.

**Strategist** (`STRATEGIST_PROMPT`):
- Replaced "default to advisor ON for advisory questions" with an explicit test: *"If I answer this with just data and one sentence of judgment, is the user satisfied?" — if yes, advisor is NOT needed.*
- Listed concrete advisor=TRUE vs advisor=FALSE shapes with goal-progress / quantification examples on the FALSE side and "rebuild plan / how to allocate" on the TRUE side.
- Added the rationale: triggering advisor unnecessarily produces canned allocation-table replies.

Key principle change: the prompts now express *intent* (match shape, avoid templates, default to data-only) rather than keyword-based routing.

### Metadata
- Source: user_feedback ("her cevap aynı format, statik kelimelerle çözülmez, promptu geliştir")
- Related Files:
  - `backend/app/agents/synthesizer.py`
  - `backend/app/agents/supervisor.py`
- Tags: prompt-engineering, anti-template, speech-acts, intent-classification

### Resolution
- **Resolved**: 2026-05-18T12:50:00Z
- **Notes**: Backend hot-reloaded. Next test: ask both "ev hedefime yetişiyor muyum" (should now be a short verification reply with numbers, no allocation table) and "ev hedefime göre nasıl yatırım yapayım" (should still produce a full plan with the allocation table) — the two replies must look structurally different.

---
