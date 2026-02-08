# RemoteAfrica Battery Fire Test

Date: 2026-02-08 (UTC)  
Board: `remoteafrica`  
Goal: Validate no-proxy baseline with bounded smoke then standard runs.

## Configs Used

- `boards/remoteafrica/config/battery.smoke.noproxy.yaml`
- `boards/remoteafrica/config/battery.standard.noproxy.yaml`

## Standardized Battery Settings Applied

- `search.keywords`: `["AI engineer"]` (informational only for RemoteAfrica global-list collection)
- `search.location`: `"Remote"`
- `search.max_pages`: smoke=`1`, standard=`2`
- `search.max_results_per_search`: smoke=`25`, standard=`50`
- `search.detail_salary_fetch`: `false`
- `search.detail_description_fetch`: `false`
- `output.*`: written under `boards/remoteafrica/output/test-runs/`
- `output.vault_sync.enabled`: `false`
- `browser.headless`: `true`
- `browser.min_delay/max_delay`: `0.4/1.2`
- `browser.navigation_timeout`: `45`
- `ai_filter.enabled`: `false`
- Baseline proxy mode: `proxy.enabled: false`

## Results

| Config | Status | Jobs | Duration | Output JSON |
|---|---|---:|---:|---|
| `battery.smoke.noproxy.yaml` | PASS | 20 | 29.45s | `boards/remoteafrica/output/test-runs/jobs_battery_smoke_noproxy_20260208_025049.json` |
| `battery.standard.noproxy.yaml` | PASS | 40 | 49.60s | `boards/remoteafrica/output/test-runs/jobs_battery_standard_noproxy_20260208_025143.json` |

## Warnings And Artifacts

- Both runs logged: `No session found - run setup_session.py first!`.
- This warning did not block collection and both runs completed successfully.
- No new debug/block artifacts were produced under `boards/remoteafrica/output/` during this run window.
- Run logs:
  - `boards/remoteafrica/logs/test-runs/battery_smoke_noproxy_20260208_025020.log`
  - `boards/remoteafrica/logs/test-runs/battery_standard_noproxy_20260208_025054.log`

## Recommendation

**Proxy not needed** for the current bounded RemoteAfrica baseline. Keep proxy variant optional and only introduce it if future runs begin failing from access/bot-block issues.
