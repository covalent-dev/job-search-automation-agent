# ISP Proxy Integration (Indeed + Glassdoor)

**Updated:** 2026-02-05

This repo’s board configs (Indeed + Glassdoor) read proxy credentials from the repo-level `.env` file (gitignored) via `${PROXY_*}` environment variable expansion.

## What Changed

- Switched from residential proxy credentials to an ISP proxy endpoint.
- No hardcoded credentials were added to the repo.
- Added bounded smoke-test configs for quick validation.

## Required Environment Variables

Set these in `/root/covalent-dev/job-search-automation-agent/.env`:

- `PROXY_HOST`
- `PROXY_PORT`
- `PROXY_USERNAME`
- `PROXY_PASSWORD`
- `CAPSOLVER_API_KEY`

Notes:
- `.env` is gitignored and should not be committed.
- Logs should not include username/password; only the proxy server host/port may appear.

## Smoke Tests

Run a small, bounded scrape (1 keyword, 1 page, 3 results max):

```bash
cd /root/covalent-dev/job-search-automation-agent

./scripts/run_board.sh indeed boards/indeed/config/smoke_test.yaml
./scripts/run_board.sh glassdoor boards/glassdoor/config/smoke_test.yaml
```

Expected success signal:

- `boards/<board>/output/run_metrics_*.json` shows `jobs_unique_collected >= 1`
- Captcha metrics show Turnstile attempts/solves when Cloudflare interstitials appear

Example checks:

```bash
ls -tr boards/indeed/output/run_metrics_*.json | tail -1
ls -tr boards/glassdoor/output/run_metrics_*.json | tail -1
```

## Results (2026-02-05)

- **Glassdoor:** Smoke test succeeded with proxy enabled; 3 jobs collected. CapSolver solved a Cloudflare interstitial during navigation and collection proceeded normally.
- **Indeed:** Smoke test did **not** collect jobs. Requests consistently landed on Cloudflare “Additional Verification Required” / “Security Check” interstitials. CapSolver attempts sometimes inject Cloudflare clearance cookies but the session remains blocked. FlareSolverr did not reliably solve the interstitial with this proxy.

## FlareSolverr (Optional)

Configs keep FlareSolverr enabled (`http://localhost:8191`) to help with non-Turnstile Cloudflare JS interstitials.

If FlareSolverr is not running, collectors will automatically skip it (the client checks `/health`) and continue with the normal CapSolver path.
