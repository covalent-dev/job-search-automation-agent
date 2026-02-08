# RemoteJobs Production Soak (Async Reliability Ramp)

Date (UTC): 2026-02-08  
Board: `remotejobs`  
Run ID: `20260208_032925`  
Artifacts: `docs/reliability/artifacts/remotejobs_production_soak_async/20260208_032925/`

## Scope and Execution Notes

- Executed production-shape configs with full detail paths enabled (salary/company/description).
- RemoteJobs persistent profile was missing during runs:
  - `~/.job-search-automation/job-search-automation-remotejobs-profile` not found.
- No-proxy loop started as 2 warmup + 10 measured, but was stopped early after measured run 3 became mathematically unable to reach the >=85% pass target (2 measured failures already observed).
- Proxy comparison was executed because no-proxy missed target; proxy loop was stopped after 3 measured runs due early convergence (same post-first-run collapse pattern).

## Config Values Used

### No-Proxy Config
File: `boards/remotejobs/config/soak.production.noproxy.yaml`

- `search.keywords`: `AI engineer`, `AI/ML engineer`, `LLM engineer`
- `search.location`: `Remote`
- `search.max_pages`: `3`
- `search.max_results_per_search`: `60`
- `search.detail_salary_fetch`: `true`
- `search.detail_salary_max_per_query`: `0`
- `search.detail_company_fetch`: `true`
- `search.detail_description_fetch`: `true`
- `search.detail_description_max_per_query`: `0`
- `output.*`: `output/test-runs/...`
- `output.summary_file`: enabled in config
- `output.config_snapshot_file`: enabled in config
- `output.vault_sync.enabled`: `false`
- `browser.headless`: `true`
- `browser.use_stealth`: `true`
- `browser.min_delay/max_delay`: `0.6/1.8`
- `browser.navigation_timeout`: `45`
- `dedupe.enabled`: `true`
- `dedupe.hash_file`: `output/test-runs/dedupe_hashes_soak_production_noproxy.jsonl`
- `ai_filter.enabled`: `false`
- `flaresolverr.enabled`: `false`
- `proxy.enabled`: `false`

### Proxy Config
File: `boards/remotejobs/config/soak.production.proxy.yaml`

- Same production-shape settings as no-proxy, except:
- `proxy.enabled`: `true`
- `proxy.provider`: `http`
- `proxy.server`: `http://${PROXY_HOST}:${PROXY_PORT}`
- `proxy.username`: `${PROXY_USERNAME}`
- `proxy.password`: `${PROXY_PASSWORD}`
- `dedupe.hash_file`: `output/test-runs/dedupe_hashes_soak_production_proxy.jsonl`

## No-Proxy Run Table

Artifact file: `docs/reliability/artifacts/remotejobs_production_soak_async/20260208_032925/run_table.tsv`

| phase | run | rc | duration_s | jobs | desc_nonempty | salary_nonempty | company_known | pass (jobs>=1) | jobs_file |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| warmup | 1 | 0 | 268 | 58 | 58 | 31 | 58 | 1 | `boards/remotejobs/output/test-runs/jobs_soak_production_noproxy_20260208_033353.json` |
| warmup | 2 | 0 | 274 | 4 | 4 | 0 | 4 | 1 | `boards/remotejobs/output/test-runs/jobs_soak_production_noproxy_20260208_033827.json` |
| measured | 3 | 0 | 272 | 0 | 0 | 0 | 0 | 0 | `boards/remotejobs/output/test-runs/jobs_soak_production_noproxy_20260208_034259.json` |
| measured | 4 | 0 | 270 | 0 | 0 | 0 | 0 | 0 | `boards/remotejobs/output/test-runs/jobs_soak_production_noproxy_20260208_034843.json` |
| measured | 5 | 143 | 135 | 0 | 0 | 0 | 0 | 0 | *(interrupt/no fresh file)* |

## Proxy Run Table

Artifact file: `docs/reliability/artifacts/remotejobs_production_soak_async/20260208_032925/proxy_comparison/run_table.tsv`

| phase | run | rc | duration_s | jobs | desc_nonempty | salary_nonempty | company_known | pass (jobs>=1) | jobs_file |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| measured | 1 | 0 | 294 | 61 | 61 | 30 | 61 | 1 | `boards/remotejobs/output/test-runs/jobs_soak_production_proxy_20260208_035804.json` |
| measured | 2 | 0 | 287 | 0 | 0 | 0 | 0 | 0 | `boards/remotejobs/output/test-runs/jobs_soak_production_proxy_20260208_040406.json` |
| measured | 3 | 0 | 284 | 0 | 0 | 0 | 0 | 0 | `boards/remotejobs/output/test-runs/jobs_soak_production_proxy_20260208_041005.json` |

## Pass-Rate and Reliability Summary

### No-Proxy (measured runs captured: 3)

- Pass rate (`jobs_count >= 1`): **0/3 = 0.0%**
- Description active (`desc_nonempty >= 1`): **0/3 = 0.0%**
- Company enrichment active (`company_known > 0`): **0/3 runs**

Target check against spec thresholds:

- Pass-rate target >=85%: **missed**
- Description activity target >=80% runs: **missed**
- Company enrichment active in >=1 measured run: **missed**

### Proxy (measured runs captured: 3)

- Pass rate (`jobs_count >= 1`): **1/3 = 33.3%**
- Description active (`desc_nonempty >= 1`): **1/3 = 33.3%**
- Company enrichment active (`company_known > 0`): **1/3 runs**

Comparison outcome:

- Proxy improved first-run yield but did **not** materially improve repeat-run reliability under the same production-shape + dedupe conditions.
- Both modes showed post-first-run collapse to `0` jobs while returning `rc=0`.

## Failure / Blocker Taxonomy

1. Cross-run yield collapse with dedupe enabled
- Signal: initial run returns jobs, subsequent runs trend to zero while process exits successfully.
- This was the dominant failure mode in both no-proxy and proxy.

2. Missing persistent browser profile (non-blocking in this run)
- Signal in logs: `No session found - run setup_session.py first!`
- Did not produce fail-fast Cloudflare block artifacts, but increases long-run risk.

3. Intermittent RemoteJobs error-page recoveries
- Signal in logs: `RemoteJobs error page detected; attempting recovery`
- Recovery occurred repeatedly, but collector continued.

## Cloudflare / Debug Artifact References

- `boards/remotejobs/output/block_event.json`: **not generated** during this run window
- `boards/remotejobs/output/debug_page.html`: present but timestamped **2026-01-30 18:04:01 UTC** (pre-existing)
- `boards/remotejobs/output/debug_screenshot.png`: present but timestamped **2026-01-30 18:04:01 UTC** (pre-existing)

Per-run logs:

- No-proxy logs: `docs/reliability/artifacts/remotejobs_production_soak_async/20260208_032925/*.log`
- Proxy logs: `docs/reliability/artifacts/remotejobs_production_soak_async/20260208_032925/proxy_comparison/*.log`

## 24/7 Recommendation

**NOT_READY_NEEDS_HARDENING**

Rationale:

- No-proxy measured reliability was 0% in captured measured runs.
- Proxy did not sustain reliability beyond first measured run.
- Missing persistent profile remains an unresolved risk factor for long-duration headless operation.

Minimum hardening before 24/7 pilot:

1. Establish persistent profile and re-run soak:
```bash
cd /root/covalent-dev/job-search-automation-agent
JOB_BOT_BOARD=remotejobs python3 shared/setup_session.py
```
2. Re-run measured soak with controlled dedupe strategy for reliability measurement (separate collection reliability from cross-run novelty depletion).
3. Add explicit run-level KPI split: `collector_success` vs `new_jobs_after_dedupe`.
