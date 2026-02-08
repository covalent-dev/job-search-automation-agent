# RemoteJobs Battery Fire Test

Date: 2026-02-08 (UTC)  
Board: `remotejobs`  
Goal: Validate no-proxy baseline with bounded smoke then standard runs.

## Configs Used

- `boards/remotejobs/config/battery.smoke.noproxy.yaml`
- `boards/remotejobs/config/battery.standard.noproxy.yaml`

## Standardized Battery Settings Applied

- `search.keywords`: `["AI engineer"]`
- `search.location`: `"Remote"`
- `search.max_pages`: smoke=`1`, standard=`2`
- `search.max_results_per_search`: smoke=`5`, standard=`20`
- `search.detail_salary_fetch`: `false`
- `search.detail_company_fetch`: `false`
- `search.detail_description_fetch`: `false`
- `output.*`: written under `boards/remotejobs/output/test-runs/`
- `output.vault_sync.enabled`: `false`
- `browser.headless`: `true`
- `browser.min_delay/max_delay`: `0.5/1.5`
- `browser.navigation_timeout`: `45`
- `ai_filter.enabled`: `false`
- Baseline proxy mode: `proxy.enabled: false`

## Results

| Config | Status | Jobs | Duration | Output JSON |
|---|---|---:|---:|---|
| `battery.smoke.noproxy.yaml` | PASS | 5 | 10s | `boards/remotejobs/output/test-runs/jobs_battery_smoke_noproxy_20260208_022544.json` |
| `battery.standard.noproxy.yaml` | PASS | 20 | 18s | `boards/remotejobs/output/test-runs/jobs_battery_standard_noproxy_20260208_022615.json` |

## Failure/Artifact Notes

- No Cloudflare fail-fast occurred during successful battery runs.
- No new block artifacts were generated (`output/debug_screenshot.png`, `output/debug_page.html`, `output/block_event.json`).
- Existing debug artifacts in `boards/remotejobs/output/` predate this run window.

## Recommendation

**No proxy needed** for current bounded RemoteJobs battery baseline.  
Optional session setup (`JOB_BOT_BOARD=remotejobs python3 shared/setup_session.py`) remains a fallback if Cloudflare behavior changes in future runs.
