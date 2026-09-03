#!/usr/bin/bash
# setup_dev.sh - Native venv + service bootstrap (no Docker)
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

echo "=== Faculty Patent Collection Portal - Development Setup ==="
echo ""

# =============================================
# 1. Backend Python setup
# =============================================
echo "1. Backend Python setup..."
cd "$BACKEND_DIR"

if [ ! -d ".venv" ]; then
    python -m venv .venv
    echo "   Created virtual environment .venv"
fi

# shellcheck source=/dev/null
source .venv/bin/activate

pip install -e ".[dev,llm,embeddings,paddle]" 2>&1 | tail -5

# =============================================
# 2. Database setup
# =============================================
echo ""
echo "2. Database setup..."
if ! psql -U postgres -lqt | grep -q faculty_portal; then
    createdb faculty_portal
    echo "   Created database faculty_portal"
else
    echo "   Database faculty_portal already exists"
fi

alembic upgrade head
echo "   Applied migrations"

alembic seed
echo "   Seeded super admin + departments"

# =============================================
# 3. Environment config
# =============================================
echo ""
echo "3. Environment config..."
if [ ! -f .env ]; then
    cp ../.env.example .env
    echo "   Copied .env.example to .env - remember to edit secrets!"
else
    echo "   .env already exists, skipping"
fi

# =============================================
# 4. Frontend setup
# =============================================
echo ""
echo "4. Frontend setup..."
cd "$FRONTEND_DIR"

npm install

# =============================================
# 5. Verify services
# =============================================
echo ""
echo "5. Verifying services..."
if command -v pg_ctl &> /dev/null; then
    echo "   PostgreSQL available"
else
    echo "   Note: Ensure PostgreSQL is running"
fi

echo ""
echo "=== Setup complete! ==="
echo "   Activate venv: source $BACKEND_DIR/.venv/bin/activate"
echo "   Run dev: see run_dev.sh"