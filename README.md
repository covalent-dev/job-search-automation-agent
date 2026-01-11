# Job Search Automation

Automated job search and aggregation using Playwright. Testing phase - v0.1 ships Week 4.

## Status: v0.0 (Testing)

Currently testing browser automation fundamentals. Session management works, locator strategies identified.

## Roadmap

**v0.0 (Week 1)**
- Playwright session management
- Tested 5 locator methods (get_by_role wins)
- Documented best practices

**v0.1 (Week 4)**
- Collect 50+ jobs from target sites
- Extract: title, company, location, description
- JSON/Markdown export

**v0.2 (Week 5)**
- Easy Apply automation (form filling, resume upload)
- Application tracking

**v1.0 (Week 6)**
- Multi-platform support
- AI job filtering (fit score)
- Daily reports

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

## Tech Stack

- Python 3.x
- Playwright (browser automation)
- Ollama + DeepSeek (AI filtering, coming v0.2)

## Setup
```bash
git clone https://github.com/covalent-dev/job-search-automation.git
cd job-search-automation

pip install playwright pyyaml pydantic
playwright install chromium

# Run the bot
python src/main.py
```

## Structure
```
job-search-automation/
├── config/
│   └── settings.yaml
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── models.py
│   └── config_loader.py
├── output/
├── logs/
├── requirements.txt
└── README.md
```

## Configuration

Edit `config/settings.yaml` to customize:
- Search keywords and location
- Output file paths
- Browser behavior (headless mode, delays)
- AI filtering options (Phase 5)
