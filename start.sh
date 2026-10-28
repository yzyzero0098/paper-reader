#!/usr/bin/env bash
# Paper Reader (macOS / Linux): build the frontend once, then serve everything on http://localhost:8000
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f frontend/dist/index.html ]; then
  echo "[paper_reader] frontend build not found - building..."
  (cd frontend && npm install && npm run build)
fi

URL="http://localhost:8000"
(command -v xdg-open >/dev/null && xdg-open "$URL" >/dev/null 2>&1) || (command -v open >/dev/null && open "$URL") || true
exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend
