# ISP Proxy Pool Glassdoor Reliability (per proxy)

**Generated:** 2026-02-06 22:20 UTC  
**Config:** `boards/glassdoor/config/reliability_smoke.yaml`  
**Pass Criteria:** `jobs_unique_collected >= 1`  
**Input:** `ISP_PROXY_ENDPOINTS` set to 4 endpoints in `host:port` form (credentials taken from `PROXY_USERNAME`/`PROXY_PASSWORD`)  
**Runs:** filter=5, measured=0, sleep=45s  
**Artifacts:** `/root/covalent-dev/job-search-automation-agent/docs/reliability/artifacts/isp_proxy_pool_reliability/reliability_20260206_214136`

## Results (Filter Phase)

| # | Proxy (masked) | Pass | Rate | blocked | captcha | solved | solver_fail | median_dur_s |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | `165.49.199.x:12323` | 0/5 | 0.0% | 0 | 0 | 0 | 0 | 80.8 |
| 2 | `168.158.89.x:12323` | 0/5 | 0.0% | 0 | 0 | 0 | 0 | 80.7 |
| 3 | `168.158.158.x:12323` | 0/5 | 0.0% | 0 | 0 | 0 | 0 | 80.9 |
| 4 | `168.158.159.x:12323` | 0/5 | 0.0% | 0 | 0 | 0 | 0 | 80.1 |

**Observed failure mode:** all attempts failed during search navigation with `Page.goto` timeouts (navigation timeout in config is 25s). No captcha/blocked counters were recorded for these runs.

## Recommendation

- **Keep:** none (0/5 across all proxies).
- **Next:** try a different proxy pool/provider, or re-test with a higher navigation timeout if you suspect these IPs are just slow.

## How To Re-Run

Phase A (filter across all proxies):
```bash
python3 scripts/proxy_pool_reliability.py --filter-runs 5 --sleep-seconds 45
```

Phase B (measured for a subset):
```bash
python3 scripts/proxy_pool_reliability.py --only-indexes 2,4 --measured-runs 10 --sleep-seconds 45
```
