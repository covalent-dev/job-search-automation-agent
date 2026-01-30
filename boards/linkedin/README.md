# LinkedIn Board

LinkedIn job collector for the Job Search Automation Agent monorepo.

## Quick Start

```bash
# From repo root
pip install -r requirements.txt
playwright install chromium

# One-time (or when session expires): create auth artifacts for LinkedIn
JOB_BOT_BOARD=linkedin python3 shared/setup_session.py

# Run collection
./scripts/run_board.sh linkedin
```

## Session / Auth State (Source of Truth)

The LinkedIn collector prefers a **persistent Playwright profile** and uses a
storage-state JSON only as a fallback.

**Preferred (persistent profile):**
- `~/.job-search-automation/job-search-automation-linkedin-profile/`

**Fallback (storage state, gitignored):**
- `boards/linkedin/config/session.json`

On startup, the collector will:
1. Use the persistent profile if it exists.
2. Otherwise, load `boards/linkedin/config/session.json` if present.
3. Otherwise, run without auth state and warn you to run setup.

**Legacy compatibility:** if `config/session.json` exists at the repo root, the
collector can still load it, but the preferred location is
`boards/linkedin/config/session.json`.

## Output

- `boards/linkedin/output/` for JSON/Markdown exports and run artifacts.
