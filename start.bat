@echo off
REM Paper Reader: build the frontend once (if needed) and serve everything on http://localhost:8000
cd /d "%~dp0"
if not exist "frontend\dist\index.html" (
  echo [paper_reader] frontend build not found - building...
  pushd frontend
  call npm install
  call npm run build
  popd
)
start "" http://localhost:8000
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend
