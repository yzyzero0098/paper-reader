@echo off
REM Development mode: backend (8000, auto-reload) + Vite dev server (5173, hot reload)
cd /d "%~dp0"
start "paper_reader backend" cmd /k python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --app-dir backend
start "paper_reader frontend" cmd /k npm run dev --prefix frontend
timeout /t 3 >nul
start "" http://localhost:5173
