#!/usr/bin/bash
# run_tests.sh - Run the test suite
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"

echo "=== Running Faculty Patent Collection Portal Tests ==="
echo ""

cd "$BACKEND_DIR"
source .venv/bin/activate

# Run unit and API tests
echo "Running unit and API tests..."
pytest -x -v 2>&1

echo ""
echo "=== Tests complete ==="