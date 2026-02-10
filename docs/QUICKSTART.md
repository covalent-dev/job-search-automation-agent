# Quick Start

Get up and running with Job Bot in 5 minutes.

## Prerequisites

- Python 3.10+
- Ollama (for AI scoring)
- Git

## Installation

```bash
# Clone the repo
git clone https://github.com/covalent-dev/job-search-automation-agent.git
cd job-search-automation-agent

# Recommended: bootstrap a repo-local virtualenv and install deps + Playwright browser
./scripts/bootstrap_env.sh

# Alternative (system Python / existing venv):
# pip install -r requirements.txt
# python -m playwright install chromium
```

## First Run (Per Board)

Each board requires a one-time browser profile setup to solve the initial captcha.

### 1. Setup Browser Profile

```bash
# Recommended (bootstraps .venv automatically):
./scripts/setup_profile.sh glassdoor

# Alternative:
# export JOB_BOT_BOARD="glassdoor"
# python3 shared/setup_session.py
```

This opens a browser window. Solve any captcha that appears, then press Enter in the terminal. Your session is now saved and you won't see captchas on future runs.

### 2. Configure Search

Edit the board's config file: `boards/glassdoor/config/settings.yaml`

```yaml
search:
  keywords:
    - "AI engineer"
    - "machine learning engineer"
  location: "Remote"
  max_results_per_search: 50
```

### 3. Run the Scraper

```bash
./scripts/run_board.sh glassdoor
```

The scraper will:
1. Search for jobs matching your keywords
2. Extract job details (title, company, location, salary)
3. Score jobs with AI (if enabled)
4. Save to `boards/glassdoor/output/jobs_TIMESTAMP.json` and `.md`

## Output

### JSON
`boards/glassdoor/output/jobs_20260122_1900.json`

Structured data with all job details, AI scores, and metadata.

### Markdown
`boards/glassdoor/output/jobs_20260122_1900.md`

Human-readable format perfect for Obsidian or any markdown viewer.

## Running Multiple Boards

Use tmux to run boards in parallel:

```bash
tmux new -s jobbot

# Window 0: Glassdoor
./scripts/run_board.sh glassdoor

# Ctrl+B then C (new window)
# Window 1: RemoteJobs
./scripts/run_board.sh remotejobs

# Ctrl+B then C (new window)
# Window 2: LinkedIn
./scripts/run_board.sh linkedin

# Switch windows: Ctrl+B then 0/1/2
# Detach: Ctrl+B then D
# Reattach: tmux attach -t jobbot
```

## Post-Run Filtering

After collection, you can reprocess the saved JSON with different filters:

```bash
cd boards/glassdoor
python3 ../../shared/post_run_sorter.py --latest --min-score 7 --top-n 20
```

Options:
- `--latest`: Use most recent output file
- `--min-score N`: Only keep jobs scored N or higher
- `--top-n N`: Keep only top N jobs
- `--no-ai`: Skip AI scoring, just apply filters

## Testing Selectors

Before a full run, test selectors on a small sample:

```bash
./scripts/test_selectors.sh glassdoor 5
```

This runs the scraper on 5 jobs and shows coverage statistics:
- Salary coverage: X/5 (X%)
- Description coverage: X/5 (X%)

Useful for validating selectors after site changes.

## Configuration

### Search Settings

```yaml
search:
  keywords: ["AI engineer"]
  location: "Remote"
  max_results_per_search: 50    # Jobs per search query
  max_pages: 2                   # Pagination limit (0 = unlimited)
  detail_salary_fetch: true      # Fetch salary from detail pages
  detail_description_fetch: false # Fetch full descriptions
```

### AI Scoring

```yaml
ai_filter:
  enabled: true                         # Score during collection
  model: "deepseek-coder-v2:latest"    # Ollama model
  min_score: 5                          # Filter threshold
```

### Post-Run Filtering

```yaml
post_run:
  exclude_keywords:
    - "therapist"
    - "nurse"
    - "sales"
  required_keywords: []
  location_filter:
    mode: "include"
    values: ["Remote", "Anywhere"]
```

## Headless Mode

Run without visible browser (blocked by some sites):

```bash
./scripts/run_board.sh glassdoor config/settings.headless.yaml
```

Note: Cloudflare blocks headless mode on Indeed. Other boards may work.

## Troubleshooting

### Captcha Appearing Again
Session expired. Run setup again:
```bash
export JOB_BOT_BOARD="glassdoor"
python3 shared/setup_session.py
```

### No Jobs Found
1. Check if selectors still work: `./scripts/test_selectors.sh glassdoor 5`
2. Check logs: `boards/glassdoor/logs/job_bot_*.log`
3. Site may have changed HTML structure (requires selector update)

### AI Scoring Not Working
1. Check Ollama is running: `ollama list`
2. Check model exists: `ollama list | grep deepseek-coder-v2`
3. Verify descriptions exist in output JSON
4. Try post-run scorer: `python3 shared/post_run_sorter.py --latest`

### Import Errors
Use the run script (sets PYTHONPATH correctly):
```bash
./scripts/run_board.sh <board>
```

Don't run `python3 shared/main.py` directly.

## Next Steps

- Read [ARCHITECTURE.md](ARCHITECTURE.md) to understand the codebase
- Read [CONTRIBUTING.md](CONTRIBUTING.md) to add new boards
- Check [RECON.md](RECON.md) for selector development process
- Join the discussion on GitHub Issues

## Available Boards

| Board | Status | Salary | Descriptions | Bot Detection Notes |
|-------|--------|--------|--------------|---------------------|
| RemoteJobs | ✅ Working | ✅ 60% | ✅ 100% | None — stable |
| Glassdoor | ✅ Working | ✅ 90%+ | ✅ Enabled | Minimal detection |
| LinkedIn | ✅ Working | ✅ 66% | ❌ Needs work | reCAPTCHA eliminated with profile |
| Indeed | ✅ Working | ✅ Partial | ❌ Disabled | ~30 detail fetches per session before Cloudflare |
| RemoteAfrica | ✅ Working | ✅ 20% | ✅ 90% | Cloudflare RUM observed |

Legend:
- ✅ = Feature enabled and working
- ❌ = Feature disabled or needs implementation
- Salary/Description percentages indicate extraction coverage

**Note:** Browser profile setup is critical for avoiding bot detection. Without the authenticated profile, LinkedIn triggers reCAPTCHA and Indeed blocks all detail page fetches.
