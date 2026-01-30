# RemoteJobs Board

RemoteJobs collector for `remotejobs.io` using Playwright.

## Run

From repo root:

```bash
./scripts/run_board.sh remotejobs config/settings.yaml
./scripts/run_board.sh remotejobs config/settings.headless.yaml
./scripts/run_board.sh remotejobs config/settings.smoke.yaml
```

## Cloudflare / Captcha

RemoteJobs is frequently protected by Cloudflare. When blocked, the collector fails fast and saves artifacts:
- `output/debug_screenshot.png`
- `output/debug_page.html`
- `output/block_event.json`

### Recommended remediation (persistent profile)

From repo root:

```bash
JOB_BOT_BOARD=remotejobs python3 shared/setup_session.py
```

Solve the challenge in the opened browser once; the profile is saved under:
`~/.job-search-automation/job-search-automation-remotejobs-profile`

Then rerun headless collection.
