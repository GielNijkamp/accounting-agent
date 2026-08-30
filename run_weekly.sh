#!/bin/zsh
# Weekly run: all four agents, read-only (propose only) — nothing is written to Moneybird.
# It produces a consolidated report (logs/report-<date>.md) and a summary notification.
# Booking stays a deliberate manual step you do after reading the report; set BOOK=1 to let
# the bank/asset agents also book their confident proposals (accruals stay year-end/manual).
set -u
BOOK=${BOOK:-0}

cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"

# Load secrets from a git-ignored .env (launchd/cron doesn't read your shell profile).
if [[ -f .env ]]; then
  set -a; source ./.env; set +a
fi
[[ -z "${ANTHROPIC_API_KEY:-}" ]] && echo "warning: ANTHROPIC_API_KEY not set — copy .env.example to .env" >&2

YEAR=$(date +%Y)
# year boundary: in Jan/Feb also include the previous year, otherwise unprocessed
# December mutations fall outside the period filter
START=$YEAR
[ "$(date +%-m)" -le 2 ] && START=$((YEAR - 1))
DAY=$(date +%Y-%m-%d)
LOG="logs/$DAY.log"
mkdir -p logs

# Track whether ANY agent failed — the block's own $? only reflects the last command,
# which would mask an earlier failure. The brace group keeps $rc in this shell.
rc=0
{
  echo "===== run $(date '+%Y-%m-%d %H:%M') ====="
  echo "--- Agent 1: bank mutations ---"
  .venv/bin/python agent1_bank.py --period "${START}01..${YEAR}12" $([ "$BOOK" = 1 ] && echo --book) || rc=1
  for Y in $(seq "$START" "$YEAR"); do
    echo; echo "--- Agent 2: tax ($Y) ---"          # read-only: accruals are a year-end/manual step
    .venv/bin/python agent2_tax.py    --fiscal-year "$Y" || rc=1
    echo; echo "--- Agent 3: capitalization + KIA ($Y) ---"
    .venv/bin/python agent3_asset.py  --fiscal-year "$Y" $([ "$BOOK" = 1 ] && echo --book) || rc=1
    echo; echo "--- Agent 4: wealth ($Y) ---"        # never books
    .venv/bin/python agent4_wealth.py --year "$Y" || rc=1
  done
} >> "$LOG" 2>&1

# Build the consolidated report from the per-agent summaries this run wrote; headline -> notification.
HEADLINE=$(.venv/bin/python report.py 2>>"$LOG" || echo "report build failed")
REPORT="logs/report-$DAY.md"
STATUS=$([ "$rc" -eq 0 ] && echo "done" || echo "WITH ERRORS")
osascript -e "display notification \"$STATUS — $HEADLINE\" with title \"Accounting agents\" subtitle \"$REPORT\"" 2>/dev/null || true
