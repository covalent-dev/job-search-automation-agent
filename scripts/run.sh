#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

if [ ! -f "$REPO_ROOT/.venv/bin/activate" ]; then
  echo "Missing venv at $REPO_ROOT/.venv. Create it before running."
  exit 1
fi

source "$REPO_ROOT/.venv/bin/activate"
python "$REPO_ROOT/src/main.py" "$@"
