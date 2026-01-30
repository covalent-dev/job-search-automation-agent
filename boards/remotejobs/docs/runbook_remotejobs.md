# RemoteJobs Runbook

## Setup

1. Install deps and Playwright browsers.
2. If Cloudflare blocks collection, run a one-time persistent-profile setup:

   ```bash
   JOB_BOT_BOARD=remotejobs python3 shared/setup_session.py
   ```

   Then solve the challenge and wait for job listings to load.

## Run

From repo root:

- Default: `./scripts/run_board.sh remotejobs config/settings.yaml`
- Headless: `./scripts/run_board.sh remotejobs config/settings.headless.yaml`
- Smoke (fast validation): `./scripts/run_board.sh remotejobs config/settings.smoke.yaml`

## Expected Outputs

- JSON + Markdown in `output/`.
- `run_summary_*.json` with per-run stats and QA checks.
- `config_snapshot_*.yaml` for reproducibility.

## Recovery

- If blocked: check `output/debug_page.html` for Cloudflare challenge and re-run session setup.
- If selectors break: update `boards/remotejobs/src/collector.py`.
