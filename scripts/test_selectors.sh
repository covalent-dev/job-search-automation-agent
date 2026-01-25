#!/bin/bash
# Test board selectors on small sample without full run

BOARD="$1"
MAX_JOBS="${2:-5}"

if [ -z "$BOARD" ]; then
    echo "Usage: ./scripts/test_selectors.sh <board> [max_jobs]"
    echo "Example: ./scripts/test_selectors.sh glassdoor 5"
    exit 1
fi

echo "🧪 Testing selectors for $BOARD (max $MAX_JOBS jobs)..."
echo ""

# Temporarily modify config to limit results
BOARD_DIR="boards/$BOARD"
CONFIG="$BOARD_DIR/config/settings.yaml"
CONFIG_BACKUP="$BOARD_DIR/config/settings.yaml.bak"

# Backup config
cp "$CONFIG" "$CONFIG_BACKUP"

# Set max_results_per_search to test limit
python3 << PYEOF
import yaml
with open("$CONFIG") as f:
    config = yaml.safe_load(f)
config['search']['max_results_per_search'] = $MAX_JOBS
config['search']['max_pages'] = 1
config['output']['use_timestamp'] = False
with open("$CONFIG", 'w') as f:
    yaml.dump(config, f, default_flow_style=False, sort_keys=False)
PYEOF

# Run board
./scripts/run_board.sh "$BOARD"

# Restore config
mv "$CONFIG_BACKUP" "$CONFIG"

echo ""
echo "✅ Test complete - check output/ for results"
echo "📊 Analyze coverage:"
echo ""
python3 << PYEOF
import json
from pathlib import Path

board = "$BOARD"
output_dir = Path(f"boards/{board}/output")
latest_json = sorted(output_dir.glob("jobs_*.json"), key=lambda p: p.stat().st_mtime)[-1]

data = json.load(latest_json.open())
jobs = data.get("jobs", [])

total = len(jobs)
with_salary = sum(1 for j in jobs if j.get("salary"))
with_desc = sum(1 for j in jobs if j.get("description"))
with_full_desc = sum(1 for j in jobs if j.get("description_full"))

print(f"Total jobs: {total}")
print(f"Salary coverage: {with_salary}/{total} ({100*with_salary/total if total else 0:.1f}%)")
print(f"Description coverage: {with_desc}/{total} ({100*with_desc/total if total else 0:.1f}%)")
print(f"Full description: {with_full_desc}/{total} ({100*with_full_desc/total if total else 0:.1f}%)")
PYEOF
