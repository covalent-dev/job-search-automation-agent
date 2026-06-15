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
    # Preserve per-run env overrides (the harness sets PROXY_* per run).
    # `.env` should only fill missing values and must not overwrite explicit overrides.
    __PROXY_SERVER_SET="${PROXY_SERVER+x}"
    __PROXY_SERVER_VAL="${PROXY_SERVER-}"
    __PROXY_HOST_SET="${PROXY_HOST+x}"
    __PROXY_HOST_VAL="${PROXY_HOST-}"
    __PROXY_PORT_SET="${PROXY_PORT+x}"
    __PROXY_PORT_VAL="${PROXY_PORT-}"
    __PROXY_USERNAME_SET="${PROXY_USERNAME+x}"
    __PROXY_USERNAME_VAL="${PROXY_USERNAME-}"
    __PROXY_PASSWORD_SET="${PROXY_PASSWORD+x}"
    __PROXY_PASSWORD_VAL="${PROXY_PASSWORD-}"

    set -a
    # shellcheck disable=SC1090
    source "$REPO_ROOT/.env"
    set +a

    [ -n "$__PROXY_SERVER_SET" ] && export PROXY_SERVER="$__PROXY_SERVER_VAL"
    [ -n "$__PROXY_HOST_SET" ] && export PROXY_HOST="$__PROXY_HOST_VAL"
    [ -n "$__PROXY_PORT_SET" ] && export PROXY_PORT="$__PROXY_PORT_VAL"
    [ -n "$__PROXY_USERNAME_SET" ] && export PROXY_USERNAME="$__PROXY_USERNAME_VAL"
    [ -n "$__PROXY_PASSWORD_SET" ] && export PROXY_PASSWORD="$__PROXY_PASSWORD_VAL"
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
