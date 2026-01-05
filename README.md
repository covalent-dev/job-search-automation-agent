# Job Bot 🤖

Automated job application system using Playwright browser automation.

## Status: v0.0 (Testing Phase)

Currently testing LinkedIn automation fundamentals before building the full application bot.

## Roadmap

- ✅ **v0.0** (Week 1, Jan 2026): Playwright testing foundation
  - Session management (login persistence)
  - Locator strategy testing (5 methods compared)
  - Best practices documented
  
- ⏳ **v0.1** (Week 4): Basic job scraping
  - Scrape 50+ jobs from Indeed
  - Extract: title, company, location, description
  - Save to CSV/database
  
- ⏳ **v0.2** (Week 5): Easy Apply automation
  - Auto-fill application forms
  - Resume upload
  - Track applications
  
- ⏳ **v1.0** (Week 6): Multi-platform + AI filtering
  - LinkedIn + Indeed + Greenhouse
  - AI filters jobs by fit score
  - Daily application reports

## Current Progress (v0.0)

### What's Been Tested

**Session Management:**
- Login cookies saved to JSON
- Persistent sessions across runs
- No re-login required

**Locator Strategies:**
Tested 5 different methods for finding "Easy Apply" button:
1. ✅ `get_by_role` - Most reliable (1 exact match)
2. ✅ `get_by_text` - Good fallback (4 matches)
3. ✅ CSS selectors - Works (3 matches)
4. ✅ XPath - Functional but fragile
5. ❌ Class names - Too brittle (LinkedIn changes frequently)

**Key Findings:**
- `get_by_role` is most stable for production use
- `wait_until="domcontentloaded"` best for React apps
- Session management prevents rate limiting

## Tech Stack

- **Python 3.x**
- **Playwright** - Browser automation
- **Ollama + DeepSeek** (future) - AI job filtering

## Installation
```bash
# Clone repo
git clone https://github.com/taxman-dev/job-bot.git
cd job-bot

# Install dependencies
pip install playwright
playwright install chromium

# Run tests
python tests/linkedin_login.py
python tests/linkedn-locater-test.py
```

## Project Structure
```
job-bot/
├── tests/               # v0.0 testing scripts
│   ├── linkedin_login.py
│   └── linkedn-locater-test.py
├── src/                 # v0.1+ production code (coming Week 4)
├── docs/                # Documentation
└── README.md
```

## Documentation

Full testing documentation and lessons learned: [Link to Obsidian docs when published]

## Timeline

- **Week 1** (Jan 5-11): Testing & learning Playwright
- **Week 4** (Jan 26-Feb 1): Build v0.1 (scraping)
- **Week 5** (Feb 2-8): Build v0.2 (automation)
- **Week 6** (Feb 9-15): Ship v1.0 (multi-platform)

---

*Built as part of systematic tech skill progression from bus driver → remote contractor*
