# LinkedIn Battery Fire Test

Date: 2026-02-08 (UTC)  
Board: `linkedin`  
Goal: Validate no-proxy baseline with bounded smoke then standard runs.

## Session Gate

- Preferred persistent profile path was not present: `~/.job-search-automation/job-search-automation-linkedin-profile/`
- Fallback auth artifact was present and used: `boards/linkedin/config/session.json`
- Runs were executed with authenticated session state (no anonymous baseline run).

## Configs Used

- `boards/linkedin/config/battery.smoke.noproxy.yaml`
- `boards/linkedin/config/battery.standard.noproxy.yaml`

## Standardized Battery Settings Applied

- `search.keywords`: `["AI engineer"]`
- `search.location`: `"Remote"`
- `search.max_pages`: smoke=`1`, standard=`2`
- `search.max_results_per_search`: smoke=`5`, standard=`10`
- `search.detail_salary_fetch`: `false`
- `search.detail_description_fetch`: `false`
- `output.*`: written under `boards/linkedin/output/test-runs/`
- `output.vault_sync.enabled`: `false`
- `browser.headless`: `true`
- `browser.min_delay/max_delay`: `1.0/2.0`
- `browser.navigation_timeout`: `45`
- `metrics.enabled`: `true` with `output_file: output/test-runs/run_metrics_{timestamp}.json`
- `ai_filter.enabled`: `false`
- Baseline proxy mode: `proxy.enabled: false`

## Results

| Config | Status | Jobs | Duration | Metrics JSON | Output JSON |
|---|---|---:|---:|---|---|
| `battery.smoke.noproxy.yaml` | PASS | 5 | 71s | `boards/linkedin/output/test-runs/run_metrics_20260208_024947.json` | `boards/linkedin/output/test-runs/jobs_battery_smoke_noproxy_20260208_024947.json` |
| `battery.standard.noproxy.yaml` | PASS | 10 | 146s | `boards/linkedin/output/test-runs/run_metrics_20260208_025218.json` | `boards/linkedin/output/test-runs/jobs_battery_standard_noproxy_20260208_025218.json` |

## Failure/Artifact Notes

- Battery logs and execution traces are stored in:
  - `docs/reliability/artifacts/linkedin_battery_fire_test/20260208_024836/`
  - Includes `compileall.txt`, `smoke.log`, `smoke.exit`, `standard.log`, `standard.exit`
- No new block/debug artifacts were produced during these runs:
  - `boards/linkedin/output/debug_screenshot.png`
  - `boards/linkedin/output/debug_page.html`
  - `boards/linkedin/output/block_event.json`
- Runtime compatibility issue discovered and fixed before successful battery execution:
  - `shared/config_loader.py` now includes LinkedIn-used methods for metrics/detail-queue/captcha-notification accessors.

## Recommendation

**Proxy not needed** for the current bounded LinkedIn battery baseline in this environment.  
Do not add proxy config unless future authenticated no-proxy runs regress.
