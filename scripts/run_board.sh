#!/bin/bash
set -e

BOARD="$1"
CONFIG="${2:-config/settings.yaml}"

if [ -z "$BOARD" ]; then
    echo "Usage: ./scripts/run_board.sh <board> [config]"
    echo "Example: ./scripts/run_board.sh glassdoor"
    echo ""
    echo "Available boards:"
    ls -1 boards/ | sed 's/^/  - /'
    exit 1
fi

BOARD_DIR="boards/$BOARD"
if [ ! -d "$BOARD_DIR" ]; then
    echo "❌ Board not found: $BOARD"
    exit 1
fi

# Get repo root (monorepo root)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$REPO_ROOT/shared:$REPO_ROOT/$BOARD_DIR/src:$PYTHONPATH"
export JOB_BOT_BOARD="$BOARD"

# Load repo-level .env if present (gitignored secrets; optional)
if [ -f "$REPO_ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$REPO_ROOT/.env"
    set +a
fi

# Set working directory to board dir (for relative config paths)
cd "$REPO_ROOT/$BOARD_DIR"

echo "🤖 Running Job Bot: $BOARD"
echo "📁 Working dir: $(pwd)"
echo "🐍 Python path: $PYTHONPATH"
echo ""

PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ]; then
    if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
        PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
    else
        PYTHON_BIN="python3"
    fi
fi

"$PYTHON_BIN" "$REPO_ROOT/shared/main.py" --config "$CONFIG"
