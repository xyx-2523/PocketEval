#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${APP_DIR}/logs"
PID_FILE="${APP_DIR}/pocket-web.pid"
PORT="${PORT:-8766}"
PYTHON_BIN="${PYTHON_BIN:-python}"

mkdir -p "$LOG_DIR"

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" || true)"
  if [[ -n "${old_pid}" ]] && kill -0 "$old_pid" 2>/dev/null; then
    kill "$old_pid" || true
    sleep 1
  fi
  rm -f "$PID_FILE"
fi

nohup "$PYTHON_BIN" "${APP_DIR}/server.py" --host 0.0.0.0 --port "$PORT" \
  > "${LOG_DIR}/server.log" 2>&1 &

echo $! > "$PID_FILE"
echo "Pocket web started on port ${PORT} with PID $(cat "$PID_FILE")"
