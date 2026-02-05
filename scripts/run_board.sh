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
# Put board src first so board-specific shims can override shared modules.
export PYTHONPATH="$REPO_ROOT/$BOARD_DIR/src:$REPO_ROOT/shared:$PYTHONPATH"
export JOB_BOT_BOARD="$BOARD"

# Load repo-level .env if present (gitignored secrets; optional)
if [ -f "$REPO_ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$REPO_ROOT/.env"
    set +a
fi

# Resolve config path:
# - By default configs are relative to the board dir (`config/settings.yaml`).
# - Allow callers to pass repo-root-relative paths like `boards/<board>/config/...`.
if [ -n "$CONFIG" ] && [ "${CONFIG#/}" = "$CONFIG" ]; then
    if [ -f "$REPO_ROOT/$BOARD_DIR/$CONFIG" ]; then
        : # board-dir-relative; keep as-is
    elif [ -f "$REPO_ROOT/$CONFIG" ]; then
        CONFIG="$REPO_ROOT/$CONFIG"
    fi
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
