#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

if [ ! -d "$REPO_ROOT/.venv" ]; then
  python3 -m venv "$REPO_ROOT/.venv"
fi

source "$REPO_ROOT/.venv/bin/activate"
pip install --upgrade pip
pip install -r "$REPO_ROOT/requirements.txt"

echo "✅ Venv ready in $REPO_ROOT/.venv"
