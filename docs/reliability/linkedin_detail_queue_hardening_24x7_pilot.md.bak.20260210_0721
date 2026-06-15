# LinkedIn Detail-Queue Hardening + 24x7 Async Pilot

Date: 2026-02-10 (UTC)  
Board: `linkedin`  
Run Type: async-style cadence pilot (`1` warmup + `12` measured; full detail extraction enabled)

## Objective

1. Eliminate the recurring detail-queue telemetry failure:
   - `JobCollector._metrics_event() got multiple values for argument 'kind'`
2. Confirm stability for 24x7 async operation using production-shape pilot cadence:
   - salary + description + detail queue enabled
   - metrics events enabled

## Root Cause + Fix (From Hardening)

### Root Cause

`boards/linkedin/src/collector.py` previously used:

- `JobCollector._metrics_event(self, kind: str, **data)`

Detail-queue error/retry payloads could include `kind=...`, colliding with the positional argument and raising:

- `JobCollector._metrics_event() got multiple values for argument 'kind'`

### Fix Landed

- Renamed `_metrics_event` event-name parameter from `kind` to `event_name`
- Renamed detail payload field from `kind` to `detail_kind`
- Added static regression guard:
  - `scripts/verify_linkedin_metrics_event.py`

## Configs Used

- No-proxy pilot: `boards/linkedin/config/pilot.async.noproxy.yaml`
- Proxy fallback pilot: `boards/linkedin/config/pilot.async.proxy.yaml`

Notes:
- Pilot configs keep cross-run dedupe off for repeatability of stability signal.
- Vault sync remains disabled.

## Artifacts

- Prior partial run (historical): `20260209_023143`
- Full-cadence run (this report): `20260210_013604`
- Artifact root: `docs/reliability/artifacts/linkedin_detail_queue_hardening_24x7_pilot/20260210_013604/`
- Run table: `.../run_table.tsv`
- Summary: `.../summary.json`
- Per-run logs: `.../*_run_*.log`

## Full-Cadence Results (Run ID `20260210_013604`)

### Per-Run Table

| Phase | Run | Exit | Dur(s) | Jobs | DescAll | Warn(kind) | Notes |
|---|---:|---:|---:|---:|---:|---:|---|
| warmup | 1 | 0 | 570 | 58 | 1 | 0 | baseline warmup |
| measured | 1 | 0 | 583 | 56 | 1 | 0 |  |
| measured | 2 | 0 | 554 | 59 | 1 | 0 |  |
| measured | 3 | 0 | 573 | 61 | 1 | 0 |  |
| measured | 4 | 0 | 569 | 57 | 1 | 0 |  |
| measured | 5 | 0 | 589 | 58 | 1 | 0 |  |
| measured | 6 | 1 | 0 | 0 | 0 | 0 | startup failure: `ModuleNotFoundError: No module named 'ollama'` |
| measured | 7 | 1 | 0 | 0 | 0 | 0 | startup failure: `ModuleNotFoundError: No module named 'ollama'` |
| measured | 8 | 0 | 567 | 60 | 1 | 0 |  |
| measured | 9 | 0 | 565 | 61 | 1 | 0 |  |
| measured | 10 | 0 | 564 | 59 | 1 | 0 |  |
| measured | 11 | 0 | 579 | 58 | 1 | 0 |  |
| measured | 12 | 0 | 572 | 61 | 1 | 0 |  |

### Gate Evaluation (Measured Runs Only)

Thresholds:
- Pass rate (`jobs_count >= 1`): `>= 85%`
- Description coverage (`desc_all`): `>= 80%`
- Warning signature `multiple values for argument 'kind'`: `0` total

Observed (`12` measured runs):
- Pass rate: `10/12 = 83.33%` -> **FAIL**
- Description coverage: `10/12 = 83.33%` -> **PASS**
- Warning signature total: `0` -> **PASS**

### Warning Signature Verification

Search over the full artifact directory for this run:
- Pattern: `multiple values for argument 'kind'`
- Result: **0 matches**

### Proxy Fallback Status

No-proxy missed the pass-rate gate, so proxy fallback was indicated by harness logic.

Proxy suite status:
- **Skipped** because required env vars were not set in harness environment:
  - `PROXY_SERVER`
  - `PROXY_USERNAME`
  - `PROXY_PASSWORD`

Harness output recorded:
- `Proxy fallback indicated but PROXY_* env vars are not set; skipping proxy suite.`

## Final Recommendation (Non-Conditional)

One of:
- `READY_FOR_24_7_PILOT`
- `READY_WITH_PROXY`
- `NOT_READY_NEEDS_HARDENING`

**NOT_READY_NEEDS_HARDENING**

Rationale:
- The original telemetry-collision signature remained absent (`0` occurrences), so the hardening fix is effective for that defect.
- However, measured pass-rate gate failed (`83.33% < 85%`) due two measured startup failures (`ModuleNotFoundError: No module named 'ollama'`).
- Proxy fallback evidence is unavailable in this run because proxy env vars were unset.

Practical next actions before 24x7 promotion:
1. Make AI dependency loading non-fatal when AI scoring is disabled (or ensure runtime dependency parity for all schedulers/runners).
2. Re-run full cadence (`1+12`) in a controlled runtime with stable dependencies.
3. If no-proxy still misses gates, rerun with proxy env vars set to collect `READY_WITH_PROXY` evidence.
