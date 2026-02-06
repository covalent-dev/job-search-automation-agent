# ISP Proxy Pool Smoke Test (Indeed + Glassdoor)

**Generated:** 2026-02-06 03:43 UTC  
**Pass Criteria:** `jobs_unique_collected >= 1`  
**Artifacts:** `/root/covalent-dev/job-search-automation-agent/docs/reliability/artifacts/isp_proxy_pool_smoke/smoke_20260206_033147`

## Results

| Proxy | Endpoint (masked) | Indeed | Glassdoor |
|---:|---|---|---|
| 1 | `165.49.199.x:12323` | ❌ (jobs=0, blocked=3, captcha=3, solved=3, fails=0) | ❌ (jobs=0, blocked=0, captcha=0, solved=0, fails=0) |
| 2 | `168.158.89.x:12323` | ❌ (jobs=0, blocked=3, captcha=3, solved=2, fails=1) | ✅ (jobs=3, blocked=1, captcha=1, solved=1, fails=0) |
| 3 | `168.158.158.x:12323` | ❌ (jobs=0, blocked=3, captcha=3, solved=2, fails=1) | ❌ (jobs=0, blocked=0, captcha=0, solved=0, fails=0) |
| 4 | `168.158.159.x:12323` | ❌ (jobs=0, blocked=3, captcha=3, solved=0, fails=3) | ✅ (jobs=3, blocked=1, captcha=1, solved=1, fails=0) |

## Recommendation

- **Indeed:** no passing proxies in this pool (all `jobs_unique_collected == 0`)
- **Glassdoor:** keep `168.158.89.x:12323`, `168.158.159.x:12323`

