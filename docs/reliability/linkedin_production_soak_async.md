# LinkedIn Production-Shape Soak Async

Date: 2026-02-08 (UTC)  
Board: `linkedin`  
Run Type: no-proxy production-shape soak (warmup + 8 measured)

## Session Gate

- Preferred persistent profile path was not present: `~/.job-search-automation/job-search-automation-linkedin-profile/`
- Fallback auth artifact was present and used: `boards/linkedin/config/session.json`
- Runs were executed with authenticated session state.

## Configs Used

- `boards/linkedin/config/soak.production.noproxy.yaml`
- `boards/linkedin/config/soak.production.proxy.yaml` (prepared only; not executed)

## Key Soak Settings Applied

- `search.keywords`: `[`"AI engineer"`, `"AI/ML engineer"`, `"LLM engineer"`]`
- `search.location`: `"Remote"`
- `search.max_pages`: `3`
- `search.max_results_per_search`: `25`
- `search.detail_salary_fetch`: `true`
- `search.detail_salary_max_per_query`: `0`
- `search.detail_description_fetch`: `true`
- `search.detail_description_max_per_query`: `0`
- `search.detail_queue.enabled`: `true`
- `search.detail_queue.concurrency`: `3`
- `search.detail_queue.max_attempts`: `3`
- `output.vault_sync.enabled`: `false`
- `metrics.enabled`: `true` with `output_file: output/run_metrics_{timestamp}.json`
- `ai_filter.enabled`: `false`
- `dedupe.enabled`: `true` with stable hash file
- `proxy.enabled`: `false` for executed soak runs

## Artifact Paths

- Primary artifact directory: `docs/reliability/artifacts/linkedin_production_soak_async/20260208_033018/`
- Corrected run table: `docs/reliability/artifacts/linkedin_production_soak_async/20260208_033018/run_table.tsv`
- Enriched run table: `docs/reliability/artifacts/linkedin_production_soak_async/20260208_033018/run_table_enriched.tsv`
- Summary JSON: `docs/reliability/artifacts/linkedin_production_soak_async/20260208_033018/summary.json`

## Run Results

### Per-Run Output Table

| Phase | Run | Exit | Jobs Saved (post-dedupe) | Non-empty `description_full` | Metrics JSON |
|---|---:|---:|---:|---:|---:|
| warmup | 1 | 0 | 58 | 58 | 1 |
| measured | 2 | 0 | 11 | 11 | 1 |
| measured | 3 | 0 | 10 | 10 | 1 |
| measured | 4 | 0 | 5 | 5 | 1 |
| measured | 5 | 0 | 4 | 4 | 1 |
| measured | 6 | 0 | 4 | 4 | 1 |
| measured | 7 | 0 | 4 | 4 | 1 |
| measured | 8 | 0 | 3 | 3 | 1 |
| measured | 9 | 0 | 2 | 2 | 1 |

### Measured-Run Threshold Check

- Measured pass target: `jobs_count >= 1` in `>= 80%` of measured runs
- Observed: `8/8` measured runs passed (`100%`)

- Description coverage target: non-empty `description_full` in `>= 75%` of measured runs
- Observed: `8/8` measured runs had non-empty descriptions (`100%`)

## Reliability Findings

- No-proxy throughput stayed functional across all measured runs.
- Cross-run dedupe removed a growing fraction of jobs, shrinking post-dedupe save counts over time (`11 -> 2`), which is expected with persistent dedupe in repeated same-query runs.
- A recurring detail-queue warning appeared in `6/8` measured runs:
  - `Detail queue failed ... JobCollector._metrics_event() got multiple values for argument 'kind'`
  - Warning logs: `measured_run_2.log`, `measured_run_3.log`, `measured_run_5.log`, `measured_run_6.log`, `measured_run_7.log`, `measured_run_9.log`

## Proxy Comparison

- Not executed.
- Reason: no-proxy met both required decision thresholds, so proxy fallback criteria were not triggered.

## Recommendation

**NOT_READY_NEEDS_HARDENING**

Rationale:
- Functional targets passed (jobs + descriptions), but repeated detail-queue warning rate (`75%` of measured runs) indicates a reliability bug in the full-feature path that should be fixed before 24/7 async scheduling.
- Recommended next hardening step: fix the `JobCollector._metrics_event()` argument conflict in detail queue error paths, then rerun a shorter confirmation soak.
