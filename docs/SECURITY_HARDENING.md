# Security Hardening — Audit & Remediation (2026-06-27)

Defensive audit of FinanceCoach run against three Claude Code CyberSecurity
skill methodologies and the fixes applied. Frameworks used:

- **Web Security** — OWASP Top 10 + OWASP API Security Top 10
- **AI / LLM Security** — OWASP LLM Top 10 (2025) + MITRE ATLAS
- **Vulnerability Scanner** — dependency / config / secrets review

> Scope note: FinanceCoach is a single-user prototype (`user_id` is the
> authenticated user; Firebase gates access). Several findings are *acceptable
> today* but flagged because they become real when the product goes multi-user
> SaaS. Those are called out per row.

## Baseline (already strong — no change needed)

- Parameterized SQL throughout (SQLAlchemy ORM); no string-built queries.
- bcrypt password hashing; Firebase ID tokens verified RS256.
- Cloud Run **refuses to boot** with the public default JWT secret (`main.py` lifespan).
- CORS locked to the Firebase origins on Cloud Run (wildcard only for local Tauri).
- Per-user ChromaDB isolation (`where={"user_id": …}`) for documents **and** a
  per-user memory collection — no cross-tenant retrieval.
- `ContextVar`-threaded `user_id` so tools can't leak across async requests.
- Per-user monthly **turn metering** gates the LLM path before any model work.
- `_safe_error_message` redacts secrets from client-facing errors.
- No secrets committed: `.env`, `*.db`, `chroma_db/`, SA-key JSON all gitignored;
  only public Firebase web config is in the bundle (by design).

## Fixed in this pass

| ID | Severity | Finding | Fix |
|----|----------|---------|-----|
| WEB-02 | High* | `finalize_checkout` accepted `user_id=None`, bypassing the ownership check if a caller ever omitted it | `user_id` now **mandatory**; ownership always enforced (`services/billing/__init__.py`) |
| WEB-05 / CFG-02 | Medium | No HTTP security headers | Backend middleware (nosniff, `X-Frame-Options: DENY`, `Referrer-Policy`, strict CSP, HSTS on cloud) + full header set incl. CSP in `firebase.json` for the SPA |
| WEB-07 | Medium | JWT TTL 30 days | Reduced to **7 days** (`FINCOACH_JWT_TTL_SECONDS` still overridable) |
| WEB-08 / AUTH-01 | Medium | No rate limiting on `/auth/*` (brute force / signup spam) | Dependency-free in-process limiter (`auth/ratelimit.py`): login 10/min, register 5/min, demo 30/min per IP; auto-on for Cloud Run |
| WEB-11 | Low | Secret redaction only covered Google keys | Expanded to JWTs, `sk-`/Bearer tokens, PEM private keys (`_SECRET_PATTERNS`) |
| WEB-01 | Low | `_touch_conversation` updated a row by id without owner scope | Now scoped to `user_id` |
| WEB-06 | Low | `ALTER TABLE` f-string quoted the table but not the column | Both identifiers quoted (still only static input) |
| WEB-12 | Low | News `q` param unbounded length | `max_length=128` |
| CFG-01 | Low | Docker image ran as root | Non-root `appuser` (uid 1000) |
| LLM-01 | Medium→High* | Indirect prompt injection: untrusted news headlines / uploaded-doc chunks entered agent context undelimited | `defang_untrusted` neutralizer on retrieved document text + explicit "untrusted content" guards in the news & document specialist prompts |

\* High when multi-user.

New tests: `backend/tests/test_security_hardening.py` (defang, secret redaction,
rate limiter). Full suite: **116 passed**; `ruff` + `tsc` clean.

## Deferred (documented, not yet changed)

- **LLM-02/06-A — user financial snapshot sent to Gemini in plaintext.** Inherent
  to the product (it's the user's own data going to the model by design). For
  multi-user: consider de-identifying the strategist snapshot and per-user
  checkpoint encryption. Not changed because de-identifying could degrade routing
  quality and is only relevant post multi-user.
- **DEP-01 — `pdfplumber` 0.11.9 parses untrusted PDFs.** No confirmed CVE; left
  pinned to avoid a broad dependency bump right before a deploy. Bump + re-test in
  a dedicated pass (`uv lock --upgrade-package pdfplumber`).
- **Account-deletion must never become an LLM tool.** Currently a HTTP-only,
  auth-gated endpoint (correct). Keep it that way; gate any future irreversible
  tool behind explicit human confirmation.

## Post-deploy check (do this once after the next frontend deploy)

The SPA **Content-Security-Policy** in `firebase.json` is the only change that
can't be fully verified locally. After deploy, open the live site, sign in, load
the landing 3D, and check the browser console for `Content-Security-Policy`
violation errors. The policy already allows Google Fonts, Firebase Auth/Firestore,
and Firebase Analytics (gtag / google-analytics). If something legitimate is
blocked, add its origin to the matching directive — or remove the CSP line to
roll back instantly (the other headers are safe and need no validation).

## Operational reminders

- Set a strong `FINCOACH_JWT_SECRET` in Cloud Run (the boot guard enforces this).
- Rotate `GEMINI_API_KEY` if it ever appears in a log; `_safe_error_message`
  scrubs it from client responses but not necessarily server logs.
- iyzico keys go in `backend/.env` / Cloud Run secrets — never in chat or git.
