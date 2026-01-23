# Job Search Automation Agent v0.2.0

Scrapes jobs from multiple boards, scores them with a local LLM, and syncs everything to Obsidian. Currently supports Indeed, Glassdoor, LinkedIn, RemoteJobs, and RemoteAfrica.

## Quick Start

```bash
# Run a specific board
./scripts/run_board.sh glassdoor

# Run with custom config
./scripts/run_board.sh indeed config/settings.headless.yaml

# Post-run AI scoring (after collection)
cd boards/glassdoor
python3 ../../shared/post_run_sorter.py --latest
```

## Structure

```
job-search-automation/
├── boards/              # Board-specific collectors and configs
│   ├── indeed/
│   ├── glassdoor/
│   ├── linkedin/
│   ├── remotejobs/
│   └── remoteafrica/
├── shared/              # Shared core (AI scorer, models, output writer)
├── scripts/             # Run scripts
└── requirements.txt
```

## What It Does

This is a monorepo that handles scraping from 5 different job boards. Each board gets its own isolated browser profile to avoid session conflicts. Jobs get scored by a local LLM running through Ollama, and everything syncs to an Obsidian vault for easy review.

Salary extraction uses board-specific selectors since every site structures their data differently. The filtering happens in two stages: first with rule-based keywords, then with AI scoring to rank what's actually relevant.

The architecture is designed to scale to 30+ boards without turning into a maintenance nightmare.

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Install Playwright browsers
playwright install chromium

# 3. First-time captcha setup (per board)
cd boards/glassdoor
python3 ../../shared/setup_session.py

# 4. Run collection
./scripts/run_board.sh glassdoor
```

## Configuration

Each board has `config/settings.yaml`:

```yaml
search:
  keywords:
    - "AI engineer"
    - "machine learning engineer"
  location: "Remote"
  max_results_per_search: 50
  detail_salary_fetch: true
  detail_description_fetch: false

ai_filter:
  enabled: true
  model: "deepseek-coder-v2:latest"

post_run:
  exclude_keywords:
    - "therapist"
    - "nurse"
    # Note: Don't add "senior", "staff", "principal" here - kills 90% of good matches
```

## Quick Board Setup

Copy an existing board directory, update the config with your search keywords and location, then implement the site-specific selectors in `collector.py`. Test with `./scripts/run_board.sh <boardname>` on a small sample before running full collection.

## Output

- **JSON**: `boards/<board>/output/jobs_TIMESTAMP.json`
- **Markdown**: `boards/<board>/output/jobs_TIMESTAMP.md`
- **Obsidian**: `~/Taxman_Progression_v4/05_Knowledge_Base/Job-Market-Data/<board>/`

## How It Works

The `shared/` directory contains all the common code - AI scoring, data models, output writing, etc. Each board in `boards/` only needs to implement its own `collector.py` with site-specific selectors. Everything else is shared.

The scraper uses Playwright for browser automation and handles all the usual annoyances (captchas, rate limits, session management). When you run a board, it collects jobs, scores them with the local LLM, filters out noise, and exports both JSON and Markdown.

## Adding a New Board

Before you enable salary or description scraping for a new board, you need to do recon. Job sites have multiple layout variations (different HTML structures for the same data), so you can't just guess at selectors.

The process: identify each layout case, document the HTML structure with screenshots, implement selectors that cover all cases, then test on a small sample. Once you hit 90%+ coverage, enable it in the config. Otherwise you'll just be debugging broken selectors constantly.

Check the recon workflow doc for the full breakdown.

## Status

| Board | Salary | Descriptions | AI Scoring | Status |
|-------|--------|--------------|------------|---------|
| Indeed | ✅ | ❌ | ✅ | Working |
| Glassdoor | ✅ | ❌ | ✅ | Working (perfect salary coverage) |
| LinkedIn | ✅ | ❌ | ✅ | Working |
| RemoteJobs | ✅ | ✅ | ✅ | Working (with descriptions) |
| RemoteAfrica | ✅ | ❌ | ✅ | Working |

## Version

v0.2.0 - Monorepo structure with 5 boards
