#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/run_standard_test_flow.sh <board> [options]

Options:
  --mode <full|battery|soak-off|soak-on|proxy-off>   Default: full
  --warmup-runs <N>                                   Default: 2
  --measured-runs <N>                                 Default: 10
  --sleep-seconds <N>                                 Default: 75

Notes:
- Uses standardized config paths under boards/<board>/config/
- Reliability signal must come from dedupe-off soak phase.
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

if [ "${1:-}" = "" ]; then
  usage
  exit 1
fi

BOARD="$1"
shift
MODE="full"
WARMUP_RUNS=2
MEASURED_RUNS=10
SLEEP_SECONDS=75

while [ "$#" -gt 0 ]; do
  case "$1" in
    --mode)
      MODE="$2"; shift 2 ;;
    --warmup-runs)
      WARMUP_RUNS="$2"; shift 2 ;;
    --measured-runs)
      MEASURED_RUNS="$2"; shift 2 ;;
    --sleep-seconds)
      SLEEP_SECONDS="$2"; shift 2 ;;
    *)
      echo "Unknown argument: $1"
      usage
      exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

CFG_DIR="boards/$BOARD/config"
OUT_DIR="boards/$BOARD/output/test-runs"

CFG_BATTERY_SMOKE="$CFG_DIR/battery.smoke.noproxy.yaml"
CFG_BATTERY_STANDARD="$CFG_DIR/battery.standard.noproxy.yaml"
CFG_SOAK_OFF="$CFG_DIR/soak.production.noproxy.dedupe_off.yaml"
CFG_SOAK_ON="$CFG_DIR/soak.production.noproxy.dedupe_on.yaml"
CFG_PROXY_OFF="$CFG_DIR/soak.production.proxy.dedupe_off.yaml"

need_file() {
  if [ ! -f "$1" ]; then
    echo "Missing required config: $1" >&2
    exit 2
  fi
}

case "$MODE" in
  battery)
    need_file "$CFG_BATTERY_SMOKE"
    need_file "$CFG_BATTERY_STANDARD"
    ;;
  soak-off)
    need_file "$CFG_SOAK_OFF"
    ;;
  soak-on)
    need_file "$CFG_SOAK_ON"
    ;;
  proxy-off)
    need_file "$CFG_PROXY_OFF"
    ;;
  full)
    need_file "$CFG_BATTERY_SMOKE"
    need_file "$CFG_BATTERY_STANDARD"
    need_file "$CFG_SOAK_OFF"
    need_file "$CFG_SOAK_ON"
    ;;
  *)
    echo "Invalid --mode: $MODE" >&2
    exit 2
    ;;
esac

python3 -m compileall -q shared boards scripts

RUN_ID="$(date -u +%Y%m%d_%H%M%S)"
ART_DIR="docs/reliability/artifacts/${BOARD}_standard_flow/${RUN_ID}"
mkdir -p "$ART_DIR"

echo "run_id=${RUN_ID}" > "$ART_DIR/meta.env"
echo "board=${BOARD}" >> "$ART_DIR/meta.env"
echo "mode=${MODE}" >> "$ART_DIR/meta.env"
echo "started_utc=$(date -u '+%Y-%m-%d %H:%M:%S')" >> "$ART_DIR/meta.env"

echo -e "suite\tphase\trun_index\trc\tduration_s\tjobs_count\tdesc_nonempty\tsalary_nonempty\tcompany_known\tpass_jobs_ge_1\tdedupe_removed\tconfig\tjobs_file" > "$ART_DIR/run_table.tsv"

latest_jobs_file() {
  find "$OUT_DIR" -maxdepth 1 -type f -name 'jobs_*.json' -printf '%T@ %p\n' 2>/dev/null | sort -nr | awk 'NR==1{print $2}'
}

run_once() {
  local suite="$1"
  local phase="$2"
  local idx="$3"
  local cfg="$4"

  local log_file="$ART_DIR/${suite}_${phase}_run_${idx}.log"
  local start_epoch
  start_epoch="$(date +%s)"

  ./scripts/run_board.sh "$BOARD" "$cfg" > "$log_file" 2>&1
  local rc=$?

  local end_epoch
  end_epoch="$(date +%s)"
  local duration_s=$((end_epoch - start_epoch))

  local jobs_path
  jobs_path="$(latest_jobs_file || true)"
  if [ -n "${jobs_path:-}" ] && [ -f "$jobs_path" ]; then
    local mtime
    mtime="$(stat -c %Y "$jobs_path")"
    if [ "$mtime" -lt "$start_epoch" ]; then
      jobs_path=""
    fi
  fi

  local dedupe_removed=0
  local dedupe_line
  dedupe_line="$(rg -n "Cross-run dedupe: [0-9]+ duplicates removed" "$log_file" | tail -n 1 || true)"
  if [ -n "$dedupe_line" ]; then
    dedupe_removed="$(echo "$dedupe_line" | sed -E 's/.*Cross-run dedupe: ([0-9]+) duplicates removed.*/\1/')"
  fi

  python3 - "$suite" "$phase" "$idx" "$rc" "$duration_s" "$dedupe_removed" "$cfg" "$jobs_path" >> "$ART_DIR/run_table.tsv" <<'PY'
import json, pathlib, sys
suite, phase, idx, rc, duration_s, dedupe_removed, cfg, jobs_path = sys.argv[1:]
count = desc = salary = company = 0
if jobs_path and pathlib.Path(jobs_path).exists():
    payload = json.loads(pathlib.Path(jobs_path).read_text(encoding='utf-8'))
    jobs = payload if isinstance(payload, list) else payload.get('jobs', []) if isinstance(payload, dict) else []
    if isinstance(jobs, list):
        count = len(jobs)
        for j in jobs:
            if not isinstance(j, dict):
                continue
            if (j.get('description_full') or '').strip() or (j.get('description') or '').strip():
                desc += 1
            if (j.get('salary') or '').strip():
                salary += 1
            c = (j.get('company') or '').strip()
            if c and c.lower() != 'unknown company':
                company += 1
pass_flag = 1 if count >= 1 else 0
print(f"{suite}\t{phase}\t{idx}\t{rc}\t{duration_s}\t{count}\t{desc}\t{salary}\t{company}\t{pass_flag}\t{dedupe_removed}\t{cfg}\t{jobs_path}")
PY

  echo "[$(date -u '+%H:%M:%S')] $suite/$phase run=$idx rc=$rc jobs_file=${jobs_path:-none}"
}

run_soak_suite() {
  local suite="$1"
  local cfg="$2"

  local i
  for i in $(seq 1 "$WARMUP_RUNS"); do
    run_once "$suite" warmup "$i" "$cfg"
  done

  for i in $(seq 1 "$MEASURED_RUNS"); do
    run_once "$suite" measured "$i" "$cfg"
    if [ "$i" -lt "$MEASURED_RUNS" ] && [ "$SLEEP_SECONDS" -gt 0 ]; then
      sleep "$SLEEP_SECONDS"
    fi
  done
}

case "$MODE" in
  battery)
    run_once battery smoke 1 "$CFG_BATTERY_SMOKE"
    run_once battery standard 1 "$CFG_BATTERY_STANDARD"
    ;;
  soak-off)
    run_soak_suite soak_dedupe_off "$CFG_SOAK_OFF"
    ;;
  soak-on)
    run_soak_suite soak_dedupe_on "$CFG_SOAK_ON"
    ;;
  proxy-off)
    run_soak_suite proxy_dedupe_off "$CFG_PROXY_OFF"
    ;;
  full)
    run_once battery smoke 1 "$CFG_BATTERY_SMOKE"
    run_once battery standard 1 "$CFG_BATTERY_STANDARD"
    run_soak_suite soak_dedupe_off "$CFG_SOAK_OFF"
    run_soak_suite soak_dedupe_on "$CFG_SOAK_ON"
    ;;
esac

echo "finished_utc=$(date -u '+%Y-%m-%d %H:%M:%S')" >> "$ART_DIR/meta.env"
echo "artifact_dir=$ART_DIR"
echo "Run table: $ART_DIR/run_table.tsv"
