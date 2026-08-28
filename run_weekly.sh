#!/bin/zsh
# Weekly run: Agent 1 (bank mutations) + Agent 3 (capitalization/KIA).
# Deliberately WITHOUT --book: the agents only make proposals; you book yourself
# after review. Only set BOOK=1 below once you trust the classification.
set -u
BOOK=${BOOK:-0}

cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
export ANTHROPIC_API_KEY=$(grep -m1 'export ANTHROPIC_API_KEY=' ~/.zshrc | cut -d= -f2)

YEAR=$(date +%Y)
# year boundary: in Jan/Feb also include the previous year, otherwise unprocessed
# December mutations fall outside the period filter
START=$YEAR
[ "$(date +%-m)" -le 2 ] && START=$((YEAR - 1))
LOG="logs/$(date +%Y-%m-%d).log"
mkdir -p logs

{
  echo "===== run $(date '+%Y-%m-%d %H:%M') ====="
  echo "--- Agent 1: bank mutations ---"
  .venv/bin/python agent1_bank.py --period "${START}01..${YEAR}12" $([ "$BOOK" = 1 ] && echo --book)
  for Y in $(seq "$START" "$YEAR"); do
    echo
    echo "--- Agent 3: capitalization + KIA ($Y) ---"
    .venv/bin/python agent3_asset.py --fiscal-year "$Y" $([ "$BOOK" = 1 ] && echo --book)
  done
} >> "$LOG" 2>&1

STATUS=$([ $? -eq 0 ] && echo "done" || echo "WITH ERRORS")
osascript -e "display notification \"Weekly run $STATUS — see $LOG\" with title \"Accounting agents\"" 2>/dev/null || true
