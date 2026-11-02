#!/usr/bin/env bash
# Paper Reader (macOS / Linux): build the frontend once, then serve everything on http://127.0.0.1:8000
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PAPER_READER_PORT:-8000}"
URL="http://127.0.0.1:${PORT}"

if [ ! -f frontend/dist/index.html ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "[paper_reader] Node.js (npm) is required to build the frontend: https://nodejs.org" >&2
    exit 1
  fi
  echo "[paper_reader] frontend build not found - building..."
  (cd frontend && npm install && npm run build)
fi

PY="$(command -v python3 || command -v python)"

# Open the browser only after the server answers (opening first shows "can't connect").
(
  for _ in $(seq 1 120); do
    if curl -fs "$URL/api/health" >/dev/null 2>&1; then
      if command -v open >/dev/null 2>&1; then open "$URL"
      elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1
      fi
      exit 0
    fi
    sleep 0.5
  done
) &

echo "[paper_reader] $URL"
exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --app-dir backend
