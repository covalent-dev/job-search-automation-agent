# Job Search Automation

Automated job search and aggregation using Playwright. Testing phase

## Status: v0.0 (Testing)

Currently testing browser automation fundamentals. Session management works, locator strategies identified.

## What's Working (v0.0)

**Session Management:**
- Saves login cookies to JSON
- No re-login needed across runs

**Locator Testing Results:**
- `get_by_role`: 1 exact match (most reliable)
- `get_by_text`: 4 matches (good fallback)
- CSS selectors: 3 matches (works)
- XPath: functional but fragile
- Class names: breaks on UI updates (avoid)

**Key Learnings:**
- `get_by_role` is production-ready
- `wait_until="domcontentloaded"` for React apps
- Never use `time.sleep()` with Playwright

**De-duplication:**
- Cross-run dedupe via hash log
- Within-run dedupe uses job links

## Tech Stack

- Python 3.x
- Playwright (browser automation)
- Ollama + DeepSeek (AI filtering, coming v0.2)

## Setup
```bash
git clone https://github.com/covalent-dev/job-search-automation.git
cd job-search-automation

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
playwright install chromium

# First time: Setup session (solve captcha once)
python src/setup_session.py --config config/settings.yaml

# Run the bot (Glassdoor default)
python src/main.py

# Run Indeed config
python src/main.py --config config/settings.indeed.yaml
```

## Session Management

Job sites use Cloudflare protection. Run `setup_session.py` first to:
1. Open a browser window
2. Solve the captcha manually
3. Save the session cookies

After setup, `main.py` reuses the saved session to bypass captcha.
Note: Playwright may open an extra `about:blank` tab for automation control. Leave it open during runs.

## Structure
```
job-search-automation/
├── config/
│   ├── settings.yaml
│   ├── settings.indeed.yaml
│   └── session.json      # Saved after setup (gitignored)
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── setup_session.py  # Run once to save session
│   ├── collector.py
│   ├── output_writer.py
│   ├── models.py
│   └── config_loader.py
├── output/
├── logs/
├── requirements.txt
└── README.md
```

## Configuration

This board ships with multiple config profiles under `config/`:
- `config/settings.yaml` - default balanced run (headless + stealth + normal delays)
- `config/settings.headless.yaml` - headless production profile (stealth enabled, extra delays)
- `config/settings.visible.yaml` - non-headless debug profile (slow, small sample, full extraction)


Edit `config/settings.yaml` to customize:
- Search keywords and location
- Output file paths
- Browser behavior (headless mode, delays)
- AI scoring options (Ollama)
- Cross-run de-duplication log

Default config targets Glassdoor. Use `config/settings.indeed.yaml` to switch back to Indeed.

Each run writes:
- JSON + Markdown output
- `run_summary_*.json` (per-run stats and QA checks)
- `config_snapshot_*.yaml` (config snapshot)

Headless runs (optional):
- `python src/main.py --config config/settings.headless.yaml`
