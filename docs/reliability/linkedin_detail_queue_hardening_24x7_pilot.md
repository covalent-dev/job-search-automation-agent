# LinkedIn Detail-Queue Hardening + 24x7 Async Pilot

Date: 2026-02-09 (UTC)  
Board: `linkedin`  
Run Type: async-style cadence pilot (warmup + measured loops; full detail extraction enabled)

## Objective

1. Eliminate the recurring detail-queue telemetry failure:
   - `JobCollector._metrics_event() got multiple values for argument 'kind'`
2. Confirm stability for 24x7 async operation using a production-shape pilot cadence with:
   - salary + description + detail queue enabled
   - metrics events enabled

## Root Cause + Fix

### Root Cause

`boards/linkedin/src/collector.py` defined:

- `JobCollector._metrics_event(self, kind: str, **data)`

Detail-queue error/retry paths also emitted payload fields like `kind=...`, which collided with the positional parameter name `kind`, producing:

- `JobCollector._metrics_event() got multiple values for argument 'kind'`

### Fix

- Renamed `_metrics_event`’s event-name parameter from `kind` to `event_name`.
- Normalized detail-queue payload to use `detail_kind` instead of `kind`.
- Added a static regression guard:
  - `scripts/verify_linkedin_metrics_event.py`

Files:
- `boards/linkedin/src/collector.py`
- `scripts/verify_linkedin_metrics_event.py`

## Configs Used

- No-proxy pilot: `boards/linkedin/config/pilot.async.noproxy.yaml`
- Proxy fallback pilot: `boards/linkedin/config/pilot.async.proxy.yaml`

Notes:
- Pilot configs intentionally disable cross-run dedupe to avoid `jobs_count == 0` from repetition rather than reliability.
- Vault sync remains disabled.

## Artifacts

- Artifact root: `docs/reliability/artifacts/linkedin_detail_queue_hardening_24x7_pilot/<RUN_ID>/`
- Run table: `.../run_table.tsv`
- Summary: `.../summary.json`
- Per-run logs: `.../*_run_*.log`

## Pilot Results

Populate from the final `run_table.tsv` and `summary.json` for the completed pilot run:

- Measured pass rate target (jobs_count >= 1): >= 85%
- Description coverage target (all saved jobs have non-empty description): >= 80%
- Warning count for the prior signature: exactly 0 across measured runs

## Recommendation

One of:
- `READY_FOR_24_7_PILOT`
- `READY_WITH_PROXY`
- `NOT_READY_NEEDS_HARDENING`

Decision and rationale will be filled in after the measured pilot completes.

