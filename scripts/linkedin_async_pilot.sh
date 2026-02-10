#!/usr/bin/env bash
set -euo pipefail

# LinkedIn detail-queue hardening pilot harness.
# Default cadence: 1 warmup + 12 measured runs with 60s sleeps between measured runs.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BOARD="linkedin"
CFG_NO_PROXY="boards/linkedin/config/pilot.async.noproxy.yaml"
CFG_PROXY="boards/linkedin/config/pilot.async.proxy.yaml"

WARMUP_RUNS="${WARMUP_RUNS:-1}"
MEASURED_RUNS="${MEASURED_RUNS:-12}"
SLEEP_SECONDS="${SLEEP_SECONDS:-60}"

WARMUP_RUNS_PROXY="${WARMUP_RUNS_PROXY:-1}"
MEASURED_RUNS_PROXY="${MEASURED_RUNS_PROXY:-6}"
SLEEP_SECONDS_PROXY="${SLEEP_SECONDS_PROXY:-60}"

PASS_TARGET_RATE="${PASS_TARGET_RATE:-0.85}"
DESC_TARGET_RATE="${DESC_TARGET_RATE:-0.80}"

SIGNATURE="multiple values for argument 'kind'"

need_file() {
  if [ ! -f "$1" ]; then
    echo "Missing required file: $1" >&2
    exit 2
  fi
}

need_file "$CFG_NO_PROXY"
need_file "$CFG_PROXY"

# Load repo .env for proxy fallback checks at harness level. Keep explicit env
# overrides from caller.
if [ -f "$REPO_ROOT/.env" ]; then
  declare -A __PRESERVE_ENV=()
  for __k in PROXY_SERVER PROXY_HOST PROXY_PORT PROXY_USERNAME PROXY_PASSWORD; do
    if [[ -v $__k ]]; then
      __PRESERVE_ENV["$__k"]="${!__k}"
    fi
  done

  set -a
  # shellcheck disable=SC1090
  source "$REPO_ROOT/.env"
  set +a

  for __k in PROXY_SERVER PROXY_HOST PROXY_PORT PROXY_USERNAME PROXY_PASSWORD; do
    if [[ -n "${__PRESERVE_ENV[$__k]+x}" ]]; then
      export "$__k=${__PRESERVE_ENV[$__k]}"
    fi
  done
fi

python3 -m compileall -q shared boards scripts
python3 scripts/verify_linkedin_metrics_event.py

RUN_ID="$(date -u +%Y%m%d_%H%M%S)"
ART_DIR="docs/reliability/artifacts/linkedin_detail_queue_hardening_24x7_pilot/${RUN_ID}"
mkdir -p "$ART_DIR"

echo "run_id=${RUN_ID}" > "$ART_DIR/meta.env"
echo "board=${BOARD}" >> "$ART_DIR/meta.env"
echo "started_utc=$(date -u '+%Y-%m-%d %H:%M:%S')" >> "$ART_DIR/meta.env"
echo "warmup_runs=${WARMUP_RUNS}" >> "$ART_DIR/meta.env"
echo "measured_runs=${MEASURED_RUNS}" >> "$ART_DIR/meta.env"
echo "sleep_seconds=${SLEEP_SECONDS}" >> "$ART_DIR/meta.env"
echo "pass_target_rate=${PASS_TARGET_RATE}" >> "$ART_DIR/meta.env"
echo "desc_target_rate=${DESC_TARGET_RATE}" >> "$ART_DIR/meta.env"

# Snapshot configs used.
cp -a "$CFG_NO_PROXY" "$ART_DIR/config_pilot.async.noproxy.yaml"
cp -a "$CFG_PROXY" "$ART_DIR/config_pilot.async.proxy.yaml"

OUT_DIR="boards/linkedin/output/test-runs"
mkdir -p "$OUT_DIR"

latest_file_after() {
  local dir="$1"
  local glob="$2"
  local after_epoch="$3"
  find "$dir" -maxdepth 1 -type f -name "$glob" -printf '%T@ %p\n' 2>/dev/null \
    | awk -v after="$after_epoch" '$1 >= after {print}' \
    | sort -nr \
    | awk 'NR==1{print $2}'
}

run_once() {
  local suite="$1"
  local phase="$2"
  local idx="$3"
  local cfg="$4"

  local log_file="$ART_DIR/${suite}_${phase}_run_${idx}.log"
  local start_epoch end_epoch duration_s rc

  start_epoch="$(date +%s)"
  set +e
  ./scripts/run_board.sh "$BOARD" "$cfg" >"$log_file" 2>&1
  rc=$?
  set -e
  end_epoch="$(date +%s)"
  duration_s=$((end_epoch - start_epoch))

  local jobs_src metrics_src
  jobs_src="$(latest_file_after "$OUT_DIR" 'jobs_*.json' "$start_epoch" || true)"
  metrics_src="$(latest_file_after "$OUT_DIR" 'run_metrics_*.json' "$start_epoch" || true)"

  local jobs_dst metrics_dst
  jobs_dst="$ART_DIR/${suite}_${phase}_run_${idx}_jobs.json"
  metrics_dst="$ART_DIR/${suite}_${phase}_run_${idx}_metrics.json"
  if [ -n "${jobs_src:-}" ] && [ -f "$jobs_src" ]; then
    cp -a "$jobs_src" "$jobs_dst"
  else
    jobs_dst=""
  fi
  if [ -n "${metrics_src:-}" ] && [ -f "$metrics_src" ]; then
    cp -a "$metrics_src" "$metrics_dst"
  else
    metrics_dst=""
  fi

  local warn_count=0
  warn_count="$(rg -c "$SIGNATURE" "$log_file" 2>/dev/null || true)"
  warn_count="${warn_count:-0}"

  python3 - "$suite" "$phase" "$idx" "$rc" "$duration_s" "$warn_count" "$cfg" "$jobs_dst" "$metrics_dst" "$log_file" >>"$ART_DIR/run_table.tsv" <<'PY'
import json
import pathlib
import sys

suite, phase, idx, rc, duration_s, warn_count, cfg, jobs_path, metrics_path, log_file = sys.argv[1:]

jobs_count = desc_nonempty = salary_nonempty = company_known = 0
desc_all = 0
metrics_present = 1 if metrics_path and pathlib.Path(metrics_path).exists() else 0

if jobs_path and pathlib.Path(jobs_path).exists():
    payload = json.loads(pathlib.Path(jobs_path).read_text(encoding="utf-8"))
    jobs = payload if isinstance(payload, list) else payload.get("jobs", []) if isinstance(payload, dict) else []
    if isinstance(jobs, list):
        jobs_count = len(jobs)
        for j in jobs:
            if not isinstance(j, dict):
                continue
            if (j.get("description_full") or "").strip() or (j.get("description") or "").strip():
                desc_nonempty += 1
            if (j.get("salary") or "").strip():
                salary_nonempty += 1
            c = (j.get("company") or "").strip()
            if c and c.lower() != "unknown company":
                company_known += 1

if jobs_count > 0 and desc_nonempty == jobs_count:
    desc_all = 1

pass_jobs_ge_1 = 1 if jobs_count >= 1 else 0

print(
    "\t".join(
        [
            suite,
            phase,
            str(idx),
            str(rc),
            str(duration_s),
            str(jobs_count),
            str(desc_nonempty),
            str(desc_all),
            str(salary_nonempty),
            str(company_known),
            str(pass_jobs_ge_1),
            str(metrics_present),
            str(warn_count),
            cfg,
            jobs_path,
            metrics_path,
            log_file,
        ]
    )
)
PY

  echo "[$(date -u '+%H:%M:%S')] ${suite}/${phase} run=${idx} rc=${rc} duration_s=${duration_s} warn_collision=${warn_count}"
}

run_suite() {
  local suite="$1"
  local cfg="$2"
  local warmup="$3"
  local measured="$4"
  local sleep_s="$5"

  local i
  for i in $(seq 1 "$warmup"); do
    run_once "$suite" warmup "$i" "$cfg"
  done
  for i in $(seq 1 "$measured"); do
    run_once "$suite" measured "$i" "$cfg"
    if [ "$i" -lt "$measured" ] && [ "$sleep_s" -gt 0 ]; then
      sleep "$sleep_s"
    fi
  done
}

echo -e "suite\tphase\trun_index\trc\tduration_s\tjobs_count\tdesc_nonempty\tdesc_all\tsalary_nonempty\tcompany_known\tpass_jobs_ge_1\tmetrics_json_present\twarning_collision_count\tconfig\tjobs_file\tmetrics_file\tlog_file" >"$ART_DIR/run_table.tsv"

run_suite noproxy "$CFG_NO_PROXY" "$WARMUP_RUNS" "$MEASURED_RUNS" "$SLEEP_SECONDS"

python3 - "$ART_DIR/run_table.tsv" "$PASS_TARGET_RATE" "$DESC_TARGET_RATE" >"$ART_DIR/summary.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
pass_target = float(sys.argv[2])
desc_target = float(sys.argv[3])

rows = []
hdr = None
for line in path.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    parts = line.split("\t")
    if hdr is None:
        hdr = parts
        continue
    rows.append(dict(zip(hdr, parts)))

def _rate(num: int, den: int) -> float:
    return (num / den) if den else 0.0

measured = [r for r in rows if r.get("phase") == "measured" and r.get("suite") == "noproxy"]
total = len(measured)
pass_cnt = sum(1 for r in measured if int(r.get("pass_jobs_ge_1") or 0) == 1)
desc_cnt = sum(1 for r in measured if int(r.get("desc_all") or 0) == 1)
warn_total = sum(int(r.get("warning_collision_count") or 0) for r in measured)

summary = {
    "measured_runs": total,
    "pass_jobs_ge_1": {"count": pass_cnt, "rate": _rate(pass_cnt, total), "target": pass_target},
    "desc_all": {"count": desc_cnt, "rate": _rate(desc_cnt, total), "target": desc_target},
    "warning_collision_total": warn_total,
}

print(json.dumps(summary, indent=2, sort_keys=True))
PY

echo "finished_utc=$(date -u '+%Y-%m-%d %H:%M:%S')" >> "$ART_DIR/meta.env"
echo "artifact_dir=$ART_DIR"
echo "Run table: $ART_DIR/run_table.tsv"
echo "Summary: $ART_DIR/summary.json"

# Optional proxy fallback if no-proxy misses pass/coverage targets.
need_proxy=0
python3 - "$ART_DIR/summary.json" <<'PY' || need_proxy=1
import json, sys
s = json.loads(open(sys.argv[1], encoding="utf-8").read())
if s["warning_collision_total"] != 0:
    raise SystemExit(1)
if float(s["pass_jobs_ge_1"]["rate"]) < float(s["pass_jobs_ge_1"]["target"]):
    raise SystemExit(1)
if float(s["desc_all"]["rate"]) < float(s["desc_all"]["target"]):
    raise SystemExit(1)
PY

if [ "$need_proxy" -ne 0 ]; then
  if [ -z "${PROXY_SERVER:-}" ] && [ -n "${PROXY_HOST:-}" ] && [ -n "${PROXY_PORT:-}" ]; then
    export PROXY_SERVER="http://${PROXY_HOST}:${PROXY_PORT}"
    echo "proxy_server_derived_from_host_port=1" >> "$ART_DIR/meta.env"
  fi
  if [ -z "${PROXY_SERVER:-}" ] || [ -z "${PROXY_USERNAME:-}" ] || [ -z "${PROXY_PASSWORD:-}" ]; then
    echo "Proxy fallback indicated but PROXY_* env vars are not set; skipping proxy suite."
    echo "proxy_suite_skipped_missing_env=1" >> "$ART_DIR/meta.env"
    exit 0
  fi
  echo "No-proxy missed targets; running proxy fallback suite."
  run_suite proxy "$CFG_PROXY" "$WARMUP_RUNS_PROXY" "$MEASURED_RUNS_PROXY" "$SLEEP_SECONDS_PROXY"
fi
