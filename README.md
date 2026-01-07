# Job Bot

Automated job applications using Playwright. Testing phase - v0.1 ships Week 4.

## Status: v0.0 (Testing)

Currently testing LinkedIn scraping fundamentals. Session management works, locator strategies identified.

## Roadmap

**v0.0 (Week 1)**
- Playwright session management (login persistence via cookies)
- Tested 5 locator methods (get_by_role wins)
- Documented best practices

**v0.1 (Week 4)**
- Scrape 50+ jobs from Indeed
- Extract: title, company, location, description
- CSV export

**v0.2 (Week 5)**
- Easy Apply automation (form filling, resume upload)
- Application tracking

**v1.0 (Week 6)**
- Multi-platform (LinkedIn, Indeed, Greenhouse)
- AI job filtering (fit score)
- Daily reports

## What's Working (v0.0)

**Session Management:**
- Saves login cookies to JSON
- No re-login needed across runs
- Bypasses rate limits

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
git clone https://github.com/taxman-dev/job-bot.git
cd job-bot

pip install playwright
playwright install chromium

# Test session management
python tests/linkedin_login.py

# Test locators
python tests/linkedn-locater-test.py
```

## Structure
```
├job-bot
│   ├ docs
│   ├ README.md
│   ├ src
│   └ tests
│       ├─linkedin_session.json (ignored)
│       ├─linkedn-locater-test.py
│       └─linkedn-test.py


## Documentation

Full testing notes in `docs/` (Playwright patterns, session management, locator strategies).


