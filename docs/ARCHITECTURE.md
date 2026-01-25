# Architecture

## Overview

Job Search Automation Agent is a monorepo containing scrapers for multiple job boards. Each board has its own isolated configuration and browser profile, while sharing common code for AI scoring, output formatting, and deduplication.

## Structure

```
job-search-automation-agent/
├── boards/              # Board-specific implementations
│   ├── indeed/
│   ├── glassdoor/
│   ├── linkedin/
│   ├── remotejobs/
│   └── remoteafrica/
├── shared/              # Common code (all boards)
├── scripts/             # Utility scripts
└── requirements.txt
```

### Board Directory

Each board contains:

```
boards/<name>/
├── config/
│   ├── settings.yaml           # Main config
│   └── settings.headless.yaml  # Headless mode config
├── src/
│   └── collector.py            # Board-specific selectors
├── output/                     # JSON/Markdown output (gitignored)
└── logs/                       # Run logs (gitignored)
```

### Shared Directory

Common code used by all boards:

```
shared/
├── main.py              # Entry point
├── ai_scorer.py         # LLM-based job scoring
├── post_run_sorter.py   # Batch processing/filtering
├── models.py            # Pydantic data models
├── output_writer.py     # JSON + Markdown export
├── dedupe_store.py      # Cross-run deduplication
├── config_loader.py     # YAML config parsing
└── setup_session.py     # Browser profile setup
```

## Key Concepts

### Per-Board Isolation

Each board operates independently:

- **Browser Profile**: `~/.job-search-automation/job-search-automation-{board}-profile`
- **Output Directory**: `boards/{board}/output/`
- **Configuration**: `boards/{board}/config/settings.yaml`
- **Environment Variable**: `JOB_BOT_BOARD={board}` identifies the active board

This prevents session bleed and allows parallel runs.

### Collector Pattern

Each board implements a `collector.py` with board-specific selectors:

```python
class JobCollector:
    def search(self, query: SearchQuery) -> List[Job]:
        # Board-specific implementation
        pass

    def _fetch_salary(self, job_url: str) -> Optional[str]:
        # Board-specific selectors
        pass
```

Shared code handles:
- Browser management
- Session persistence
- AI scoring
- Output formatting
- Deduplication

### Two-Stage Processing

**Stage 1: Collection**
- Scrape job listings with Playwright
- Extract basic info (title, company, location, link)
- Optional: Fetch salary from detail pages
- Optional: Fetch full description
- Optional: AI scoring during collection

**Stage 2: Post-Run Filtering** (optional)
- Load saved JSON
- Apply rule-based filters (keywords, location, etc.)
- AI scoring on survivors
- Export top N jobs

### Configuration System

YAML-based configuration per board:

```yaml
search:
  keywords:
    - "AI engineer"
    - "machine learning engineer"
  location: "Remote"
  max_results_per_search: 50
  detail_salary_fetch: true
  detail_description_fetch: true   # Enable after validating selectors for the board

ai_filter:
  enabled: true
  model: "deepseek-coder-v2:latest"

post_run:
  exclude_keywords:
    - "therapist"
    - "nurse"
    # Note: Don't add "senior", "staff", "principal"
```

## Scaling Strategy

The monorepo architecture supports 30+ boards:

1. **Shared Code**: Updates propagate to all boards instantly
2. **Minimal Board Code**: Only selectors need customization
3. **Universal Scripts**: Single run script works for all boards
4. **Parallel Execution**: Run multiple boards in tmux simultaneously

Adding a new board:
1. Copy existing board directory
2. Update config (keywords, location)
3. Implement board-specific selectors in `src/collector.py`
4. Test with `./scripts/test_selectors.sh <board> 5`
5. Full run with `./scripts/run_board.sh <board>`

## AI Scoring

Local LLM scoring via Ollama:

- **Model**: DeepSeek Coder v2 (or any Ollama model)
- **Input**: Job description text
- **Output**: Score (1-10) + brief notes
- **Filtering**: Jobs without descriptions are skipped

Scoring can happen:
- During collection (config: `ai_filter.enabled: true`)
- After collection (tool: `post_run_sorter.py --latest`)

## Deduplication

Cross-run deduplication prevents re-scraping:

- **Hash Log**: JSONL file stores job hashes
- **Primary Key**: Board-specific job ID when available
- **Fallback**: Hash of title + company + location
- **Normalization**: Indeed `jk` IDs normalized for stability

## Browser Automation

Playwright-based scraping with:

- **Session Persistence**: Saved cookies eliminate login requirements
- **Captcha Handling**: Manual intervention with user prompts
- **Error Recovery**: Checkpoint every 25 jobs
- **Rate Limiting**: Randomized delays between requests
- **Cloudflare Handling**: Non-headless mode required

## Output Format

### JSON
Structured data for programmatic access:

```json
{
  "metadata": {
    "timestamp": "2026-01-22T19:00:00",
    "board": "glassdoor",
    "total_jobs": 121
  },
  "jobs": [
    {
      "title": "Senior AI Engineer",
      "company": "Example Corp",
      "location": "Remote",
      "salary": "$120K-$180K",
      "job_type": "Full-time",
      "link": "https://...",
      "date_posted": "2 days ago",
      "description": "...",
      "ai_score": 8,
      "ai_notes": "Strong match..."
    }
  ]
}
```

### Markdown
Human-readable format for Obsidian integration:

```markdown
# Glassdoor Jobs - 2026-01-22

**Total:** 121 jobs

## Senior AI Engineer - Example Corp
- **Location:** Remote
- **Salary:** $120K-$180K
- **Posted:** 2 days ago
- **AI Score:** 8/10
- **Notes:** Strong match...
- **Link:** [Apply](https://...)
```

## Design Decisions

### Monorepo Over Separate Repos
**Why**: Scaling to 30+ boards requires unified structure. Shared code maintenance would be impossible with separate repos.

### Environment Variable Board Isolation
**Why**: Path-based detection doesn't work in monorepo. Environment variable approach maintains isolation while supporting unified structure.

### Descriptions OFF by Default (for new boards)
**Why**: Each board has different HTML structures. Enabling without recon leads to broken selectors or missing data. After recon validation, descriptions can be enabled per-board. Currently enabled: RemoteJobs (100%), Glassdoor, RemoteAfrica (90% via JSON-LD). Disabled: LinkedIn (needs detail-pane extraction), Indeed (Cloudflare rate limiting).

### Remove Seniority Keywords from Excludes
**Why**: Keywords like "senior", "staff", "principal" appear in 90% of relevant AI engineer jobs. Better to let AI scoring rank them than hard-exclude.

### Case-Based Recon Methodology
**Why**: Job boards have 3-5 layout variations for the same data. Documenting each case achieves 90%+ coverage vs 30% with naive selectors.

## Security

- **Session Files**: `config/session.json` files are gitignored (contain auth tokens)
- **API Keys**: Not required (uses local Ollama)
- **Output**: Gitignored (may contain personal data)
- **Logs**: Gitignored (may contain debug info)

## Performance

- **Rate Limiting**: Randomized delays (0.5-2s) prevent blocks
- **Parallel Boards**: Run multiple boards simultaneously in tmux
- **Checkpointing**: Progress saved every 25 jobs
- **Deduplication**: Prevents re-scraping known jobs
- **Detail Fetch Limits**: Configurable caps to control runtime

## Future Enhancements

- Board template directory for easy new board setup
- Shared BaseCollector class to reduce board-specific code
- Move profile path logic to shared utility (prevent path mismatches)
- LinkedIn detail-pane extraction for descriptions
- Indeed Cloudflare hardening (stealth mode, rate limiting, session rotation)
- Additional AI models and scoring strategies
- Headless mode compatibility testing per board
