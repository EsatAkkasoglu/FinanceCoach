#!/bin/bash
# SessionStart hook — installs project dependencies so tests and linters work
# in Claude Code on the web sessions.
#
#   Frontend (repo root): pnpm install   → node_modules for tsc/vitest
#   Backend  (backend/):  uv sync         → .venv for ruff/pytest
#
# Synchronous + idempotent. Uses `pnpm install` / `uv sync` (not the frozen-CI
# variants) so the cached container state is reused on later runs.
set -euo pipefail

# Only run in Claude Code on the web (remote) environments; local sessions
# manage their own dependencies.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

echo "[session-start] installing frontend deps (pnpm)…"
pnpm install --prefer-offline

echo "[session-start] installing backend deps (uv)…"
uv sync --project backend

echo "[session-start] done."
