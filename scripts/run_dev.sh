#!/usr/bin/bash
# run_dev.sh - uvicorn + vite
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

echo "=== Starting Faculty Patent Collection Portal Development ==="
echo ""

# =============================================
# 1. Backend - uvicorn
# =============================================
echo "1. Starting backend (uvicorn)..."
cd "$BACKEND_DIR"
source .venv/bin/activate
export $(grep -v '^#' .env | xargs)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &
UVICORN_PID=$!

# Document processing runs in-process via FastAPI BackgroundTasks (no Celery worker).

# =============================================
# 2. Frontend - vite
# =============================================
echo "2. Starting frontend (vite)..."
cd "$FRONTEND_DIR"
npm run dev -- --host &
VITE_PID=$!

echo ""
echo "=== Development servers running ==="
echo "   Backend:   http://localhost:8000 (PID: $UVICORN_PID)"
echo "   API docs:  http://localhost:8000/docs"
echo "   Frontend:  http://localhost:5173 (PID: $VITE_PID)"
echo "   Press Ctrl+C to stop all processes..."

# Wait for interrupt
trap "echo 'Stopping...'; kill $UVICORN_PID $VITE_PID 2>/dev/null; exit 0" INT TERM

wait