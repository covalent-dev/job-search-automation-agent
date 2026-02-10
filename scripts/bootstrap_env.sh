#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/bootstrap_env.sh [--venv <path>] [--python <python>] [--browser <name>] [--skip-browsers]

Creates (or repairs) the repo-local virtualenv and installs dependencies.

Defaults:
- venv:   .venv
- python: python3
- browser: chromium

Notes:
- If the venv looks machine-copied/broken (e.g. pip shebang points to /root/... on macOS),
  the script will move it aside to .venv.bak.<timestamp> and recreate it.
- Playwright's Python package is installed via requirements.txt, but browser binaries are
  installed separately via: python -m playwright install <browser>.
EOF
}

VENV_REL=".venv"
PYTHON_BIN="python3"
PW_BROWSER="chromium"
SKIP_BROWSERS=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --venv) VENV_REL="$2"; shift 2 ;;
    --python) PYTHON_BIN="$2"; shift 2 ;;
    --browser) PW_BROWSER="$2"; shift 2 ;;
    --skip-browsers) SKIP_BROWSERS=1; shift 1 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV_DIR="$REPO_ROOT/$VENV_REL"

venv_is_broken() {
  # Missing python is always broken.
  if [ ! -x "$VENV_DIR/bin/python" ]; then
    return 0
  fi

  # If pip exists and its shebang points at a non-existent interpreter, the venv was
  # likely copied from another machine.
  if [ -f "$VENV_DIR/bin/pip" ]; then
    local first
    first="$(head -n 1 "$VENV_DIR/bin/pip" 2>/dev/null || true)"
    if [[ "$first" == '#!'* ]]; then
      local interp="${first:2}"
      if [ -n "$interp" ] && [ ! -x "$interp" ]; then
        return 0
      fi
    fi
  fi

  return 1
}

ensure_venv() {
  if [ -d "$VENV_DIR" ] && venv_is_broken; then
    local ts
    ts="$(date -u +%Y%m%d_%H%M%S)"
    echo "Detected broken venv at $VENV_DIR"
    echo "Moving aside to ${VENV_DIR}.bak.${ts}"
    mv "$VENV_DIR" "${VENV_DIR}.bak.${ts}"
  fi

  if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "Creating venv at $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
  fi
}

ensure_venv

VENV_PY="$VENV_DIR/bin/python"

echo "Upgrading pip tooling"
"$VENV_PY" -m pip install -U pip setuptools wheel

echo "Installing Python dependencies (requirements.txt)"
"$VENV_PY" -m pip install -r requirements.txt

echo "Sanity check: import playwright"
"$VENV_PY" - <<'PY'
import playwright  # noqa: F401
print("OK: playwright importable")
PY

if [ "$SKIP_BROWSERS" -eq 0 ]; then
  echo "Installing Playwright browser binaries: $PW_BROWSER"
  "$VENV_PY" -m playwright install "$PW_BROWSER"
fi

echo ""
echo "Bootstrap complete."
echo "Python: $VENV_PY"
echo "Tip: run boards via ./scripts/run_board.sh <board> (it will prefer .venv automatically)."

