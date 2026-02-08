# RemoteAfrica Production-Shape Soak Async Report

Date: 2026-02-08 (UTC)  
Board: `remoteafrica`  
Goal: Production-shape reliability ramp with full detail extraction and async-style repeated runs.

## Config Used

- `boards/remoteafrica/config/soak.production.noproxy.yaml`

Key settings:
- `search.keywords`: `["AI engineer"]` (informational only for RemoteAfrica global-list collection)
- `search.location`: `"Remote"`
- `search.max_pages`: `4`
- `search.max_results_per_search`: `120`
- `search.detail_salary_fetch`: `true`
- `search.detail_description_fetch`: `true`
- `search.detail_description_max_per_query`: `0`
- `output.*`: `boards/remoteafrica/output/test-runs/`
- `output.vault_sync.enabled`: `false`
- `browser.headless`: `true`
- `browser.min_delay/max_delay`: `0.4/1.4`
- `browser.navigation_timeout`: `45`
- `dedupe.enabled`: `true` with stable hash file `output/test-runs/soak_production_dedupe_hashes.jsonl`
- `ai_filter.enabled`: `false`
- `proxy.enabled`: `false`

## Artifact Directory

- `docs/reliability/artifacts/remoteafrica_production_soak_async/20260208_033655/`
- Run table: `docs/reliability/artifacts/remoteafrica_production_soak_async/20260208_033655/run_table.tsv`

## Run Table Summary

Notes:
- `raw_collected` is parsed from collector logs before cross-run dedupe.
- `saved_jobs`/`desc_nonempty`/`salary_nonempty` are from written JSON after dedupe.

| Phase | Run | Raw Collected | Dedupe Removed | Saved Jobs | Desc Non-Empty | Salary Non-Empty | Duration (s) | Jobs JSON |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| warmup | 1 | 80 | 0 | 80 | 80 | 6 | 108 | `boards/remoteafrica/output/test-runs/jobs_soak_production_noproxy_20260208_033843.json` |
| measured | 2 | 80 | 80 | 0 | 0 | 0 | 115 | `boards/remoteafrica/output/test-runs/jobs_soak_production_noproxy_20260208_034038.json` |
| measured | 3 | 80 | 80 | 0 | 0 | 0 | 112 | `boards/remoteafrica/output/test-runs/jobs_soak_production_noproxy_20260208_034330.json` |
| measured | 4 | 80 | 80 | 0 | 0 | 0 | 104 | `boards/remoteafrica/output/test-runs/jobs_soak_production_noproxy_20260208_034614.json` |
| measured | 5 | 80 | 80 | 0 | 0 | 0 | 110 | `boards/remoteafrica/output/test-runs/jobs_soak_production_noproxy_20260208_034904.json` |
| measured | 6 | 80 | 80 | 0 | 0 | 0 | 115 | `boards/remoteafrica/output/test-runs/jobs_soak_production_noproxy_20260208_035159.json` |
| measured | 7 | 80 | 80 | 0 | 0 | 0 | 119 | `boards/remoteafrica/output/test-runs/jobs_soak_production_noproxy_20260208_035458.json` |
| measured | 8 | 80 | 80 | 0 | 0 | 0 | 114 | `boards/remoteafrica/output/test-runs/jobs_soak_production_noproxy_20260208_035752.json` |
| measured | 9 | 74 | 74 | 0 | 0 | 0 | 115 | `boards/remoteafrica/output/test-runs/jobs_soak_production_noproxy_20260208_040047.json` |
| measured | 10 | 80 | 80 | 0 | 0 | 0 | 113 | `boards/remoteafrica/output/test-runs/jobs_soak_production_noproxy_20260208_040341.json` |
| measured | 11 | 80 | 80 | 0 | 0 | 0 | 107 | `boards/remoteafrica/output/test-runs/jobs_soak_production_noproxy_20260208_040628.json` |

## Pass Rate, Description Coverage, And Failure Pattern

- Measured runs executed: `10/10`
- No-proxy measured pass rate (`raw_collected >= 1`): `100%` (`10/10`)
- No sustained crash streaks: `0` runs with `raw_collected=0`
- Measured `saved_jobs >= 1`: `0%` (`0/10`) due expected cross-run dedupe suppression, not collection failure
- Description extraction verified active: warmup saved `80/80` with non-empty `description_full`
- Measured saved description coverage remained `0/10` because dedupe removed all repeated jobs before save

## Dedupe And Async-Readiness Observations

- Dedupe behavior is strong and consistent: measured runs removed nearly all collected jobs (`74-80` removed/run).
- Collector-side throughput remained stable across measured runs (`raw_collected` mostly `80`, one transient dip to `74`, recovered next run).
- Duration remained stable without upward drift: measured range `104-119s`, average `112.4s`.
- No selector drift evidence and no debug/block artifacts created under `boards/remoteafrica/output/`.
- Warning repeated in all runs: `No session found - run setup_session.py first!` (non-blocking).

## Proxy Variant Decision

Proxy variant was **not executed**. No-proxy did not show material reliability degradation (no hard failures, no crash streaks, stable runtime/collection).

## Recommendation

`READY_FOR_24_7_PILOT`

Rationale: no-proxy collection reliability and duration stability were strong in production-shape repeated runs. For operational monitoring, treat post-dedupe `saved_jobs` as a dedupe-state signal and monitor pre-dedupe collector counts/logs for true availability health.
