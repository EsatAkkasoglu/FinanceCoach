#!/usr/bin/env bash
# Drive the crypto strategy experiment for a fixed wall-clock window.
#
# Runs one cycle every INTERVAL seconds until DEADLINE, then stops. The deadline
# is persisted on first start and re-read afterwards, so a restart (container
# reclaimed, process killed, scheduled heal) RESUMES the original 8-hour window
# instead of silently extending it — an experiment whose end time moves every
# time it crashes is not a fixed-length experiment.
#
# Usage:
#   scripts/experiment_loop.sh [hours] [interval_seconds]
#
# Defaults: 8 hours, 900s (15 min — the fastest timeframe under test).

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

HOURS="${1:-8}"
INTERVAL="${2:-900}"
DIR="data/experiment"
DEADLINE_FILE="$DIR/deadline"
LOG="$DIR/loop.log"
PID_FILE="$DIR/loop.pid"

mkdir -p "$DIR"

# Refuse to run twice — two loops would double-trade the same paper book.
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null; then
  echo "loop already running as PID $(cat "$PID_FILE") — nothing to do" | tee -a "$LOG"
  exit 0
fi
echo $$ > "$PID_FILE"

if [ -f "$DEADLINE_FILE" ]; then
  DEADLINE="$(cat "$DEADLINE_FILE")"
  echo "$(date -u +%FT%TZ) resuming existing window, deadline=$DEADLINE" | tee -a "$LOG"
else
  DEADLINE=$(( $(date +%s) + HOURS * 3600 ))
  echo "$DEADLINE" > "$DEADLINE_FILE"
  echo "$(date -u +%FT%TZ) starting ${HOURS}h window, deadline=$DEADLINE" | tee -a "$LOG"
fi

while true; do
  NOW=$(date +%s)
  if [ "$NOW" -ge "$DEADLINE" ]; then
    echo "$(date -u +%FT%TZ) deadline reached — experiment window closed" | tee -a "$LOG"
    rm -f "$PID_FILE"
    exit 0
  fi

  echo "$(date -u +%FT%TZ) --- cycle start ($(( (DEADLINE - NOW) / 60 )) min remaining)" >> "$LOG"
  # A failing cycle must not end the run: the next one re-reads state from disk.
  timeout 1500 uv run python scripts/run_experiment.py --cycle >> "$LOG" 2>&1 \
    || echo "$(date -u +%FT%TZ) cycle failed (exit $?) — continuing" >> "$LOG"

  # Recompute the sleep AFTER the cycle so a slow tournament does not push the
  # cadence out; if a cycle overran the interval, start the next one immediately.
  ELAPSED=$(( $(date +%s) - NOW ))
  SLEEP=$(( INTERVAL - ELAPSED ))
  [ "$SLEEP" -lt 30 ] && SLEEP=30
  sleep "$SLEEP"
done
