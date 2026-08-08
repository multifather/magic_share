#!/usr/bin/env bash
# magic_share / run.sh — launcher for macOS & Linux
# Mirrors run.bat. This file lives in repo root; the stand code is in
# project_stat/. Runs the demo stand: hidden server + visible watcher +
# visible generator + file manager + default browser, then 2x2 arrange.
set -u
# repo root = parent of this script's dir; stand is in project_stat/
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/project_stat/script" || exit 1

LOG="$ROOT/run_all_diag.log"
: > "$LOG"
echo "[$(date)] run.sh started; cwd=$(pwd)" >> "$LOG"

# resolve python
PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "ERROR: python3 not found. Install Python 3.10+ and retry." | tee -a "$LOG"
  exit 1
fi
echo "[$(date)] python=$PY" >> "$LOG"

# --- kill any previous stand (match our window titles / processes) ---
pkill -f "watcher.py --watch" 2>/dev/null || true
pkill -f "gen_test_data.py --interactive" 2>/dev/null || true
pkill -f "server.py" 2>/dev/null || true
sleep 1

# --- reset DB + incoming CSVs ---
rm -f "../workflow/production.db" >> "$LOG" 2>&1
rm -f ../test_reports/*.csv ../test_reports/archive/*.csv >> "$LOG" 2>&1
rm -f ../workflow/reports/stat_report_*.html >> "$LOG" 2>&1

# --- launch SERVER hidden (background, no terminal) ---
"$PY" server.py >> "$LOG" 2>&1 &
SERVER_PID=$!
echo "[$(date)] server pid=$SERVER_PID" >> "$LOG"
sleep 1

# --- launch WATCHER (new terminal window) ---
if command -v osascript >/dev/null 2>&1; then
  osascript -e "tell app \"Terminal\" to do script \"cd $(pwd) && $PY watcher.py --watch\""
elif command -v gnome-terminal >/dev/null 2>&1; then
  gnome-terminal -- bash -c "$PY watcher.py --watch; exec bash"
elif command -v xterm >/dev/null 2>&1; then
  xterm -e "$PY watcher.py --watch" &
else
  "$PY" watcher.py --watch &
fi

# --- launch GENERATOR (new terminal window) ---
if command -v osascript >/dev/null 2>&1; then
  osascript -e "tell app \"Terminal\" to do script \"cd $(pwd) && $PY gen_test_data.py --interactive --seed 42\""
elif command -v gnome-terminal >/dev/null 2>&1; then
  gnome-terminal -- bash -c "$PY gen_test_data.py --interactive --seed 42; exec bash"
elif command -v xterm >/dev/null 2>&1; then
  xterm -e "$PY gen_test_data.py --interactive --seed 42" &
else
  "$PY" gen_test_data.py --interactive --seed 42 &
fi

# --- file manager + default browser in a SEPARATE NEW window ---
( open "../test_reports" 2>/dev/null || xdg-open "../test_reports" 2>/dev/null || true )
sleep 1
# macOS: 'open -n' = new instance (standalone window). Linux: try --new-window.
if command -v osascript >/dev/null 2>&1; then
  open -n "http://127.0.0.1:8770/" 2>/dev/null || open "http://127.0.0.1:8770/" 2>/dev/null || true
else
  ( xdg-open "http://127.0.0.1:8770/" 2>/dev/null || true )
  # best-effort: if a known browser exists, force a new window
  for B in google-chrome chromium chromium-browser brave-browser firefox; do
    if command -v "$B" >/dev/null 2>&1; then
      "$B" --new-window "http://127.0.0.1:8770/" >/dev/null 2>&1 &
      break
    fi
  done
fi

# --- arrange 2x2 (macOS via AppleScript; Linux skipped, manual arrange) ---
sleep 3
if command -v osascript >/dev/null 2>&1; then
  osascript "$ROOT/layout_mac.scpt" >> "$LOG" 2>&1 || true
fi

echo "[$(date)] windows placed. Generation runs in the GENERATOR terminal." | tee -a "$LOG"
echo
echo "  Demo stand ready. Generation runs in the GENERATOR terminal; watcher auto-processes."
echo "  Press [N] for new data, [E] to exit."
echo "  Log: $LOG"
sleep 2
exit 0
