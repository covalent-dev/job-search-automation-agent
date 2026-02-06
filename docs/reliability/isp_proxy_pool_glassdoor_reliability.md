# ISP Proxy Pool Glassdoor Reliability (per proxy)

**Generated:** 2026-02-06 05:49 UTC  
**Config:** `boards/glassdoor/config/reliability_smoke.yaml`  
**Pass Criteria:** `jobs_unique_collected >= 1`  
**Input:** `ISP_PROXY_ENDPOINTS` was unset; used `PROXY_*` env vars as a single-endpoint pool  
**Runs:** filter=5, measured=10, sleep=45s  
**Artifacts:**  
- `/root/covalent-dev/job-search-automation-agent/docs/reliability/artifacts/isp_proxy_pool_reliability/reliability_20260206_052200` (filter)  
- `/root/covalent-dev/job-search-automation-agent/docs/reliability/artifacts/isp_proxy_pool_reliability/reliability_20260206_053010` (measured)

## Results (Filter Phase)

| # | Proxy (masked) | Pass | Rate | blocked | captcha | solved | solver_fail | median_dur_s |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | `165.254.97.x:12323` | 5/5 | 100.0% | 5 | 5 | 5 | 0 | 59.5 |

## Results (Measured Phase)

| # | Proxy (masked) | Pass | Rate | blocked | captcha | solved | solver_fail | median_dur_s |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | `165.254.97.x:12323` | 10/10 | 100.0% | 10 | 10 | 10 | 0 | 58.6 |

## Recommendation

- **Keep:** 1 (`165.254.97.x:12323`)

## Notes

- This run only exercised **one** endpoint (single-proxy fallback). To benchmark the full pool, set `ISP_PROXY_ENDPOINTS` locally (gitignored) to a comma-separated list of `host:port:username:password` entries.

## How To Re-Run

Phase A (filter across all proxies):
```bash
python3 scripts/proxy_pool_reliability.py --filter-runs 5 --sleep-seconds 45
```

Phase B (measured for a subset):
```bash
python3 scripts/proxy_pool_reliability.py --only-indexes 2,4 --measured-runs 10 --sleep-seconds 45
```
