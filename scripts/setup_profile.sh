#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/setup_profile.sh <board>

Creates/updates the persistent browser profile for a board by running:
  shared/setup_session.py

Notes:
- This is a headful flow (opens a real browser window). If you're on a headless VPS,
  run this on your Mac instead.
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

BOARD="${1:-}"
if [ -z "$BOARD" ]; then
  usage
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

UNAME_S="$(uname -s || true)"
if [ "$UNAME_S" = "Linux" ] && [ -z "${DISPLAY:-}" ]; then
  echo "No DISPLAY detected (headless Linux). Session setup is headful." >&2
  echo "Run this on your Mac instead:" >&2
  echo "" >&2
  echo "  cd ~/covalent-dev/job-search-automation-agent" >&2
  echo "  ./scripts/setup_profile.sh $BOARD" >&2
  exit 2
fi

# Ensure venv + deps are present.
./scripts/bootstrap_env.sh

export JOB_BOT_BOARD="$BOARD"
"$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/shared/setup_session.py"

