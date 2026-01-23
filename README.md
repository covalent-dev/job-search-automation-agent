# Job Search Automation

Automated job collection and AI-powered filtering across multiple job boards.

**Current Boards:** Indeed, Glassdoor, LinkedIn, RemoteJobs, RemoteAfrica

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

## Features

- **Multi-board support**: 5 boards, easily extensible to 30+
- **Browser sandboxing**: Isolated profiles per board (prevents session bleed)
- **AI scoring**: Local LLM via Ollama for job ranking
- **Salary extraction**: Board-specific selectors for accurate salary data
- **Obsidian integration**: Auto-sync to vault for easy browsing
- **Smart filtering**: Rule-based + AI scoring for relevant jobs only

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
    # (removed "senior", "staff", "principal" to avoid filtering good matches)
```

## Adding New Boards

1. Copy `boards/template/` to `boards/newboard/`
2. Update `config/settings.yaml` (set `job_boards: ["newboard"]`)
3. Implement board-specific selectors in `src/collector.py`
4. Test: `./scripts/run_board.sh newboard`

## Output

- **JSON**: `boards/<board>/output/jobs_TIMESTAMP.json`
- **Markdown**: `boards/<board>/output/jobs_TIMESTAMP.md`
- **Obsidian**: `~/Taxman_Progression_v4/05_Knowledge_Base/Job-Market-Data/<board>/`

## Architecture

**Shared Core** (`shared/`):
- `main.py` - Entry point
- `ai_scorer.py` - LLM scoring via Ollama
- `post_run_sorter.py` - Rule filter + AI scoring on saved JSON
- `models.py` - Pydantic data models
- `output_writer.py` - JSON/Markdown export
- `setup_session.py` - Captcha solver (manual)

**Board-Specific** (`boards/<name>/src/`):
- `collector.py` - Playwright scraping with board-specific selectors

## Recon Workflow

Before enabling detailed scraping (salary, descriptions), perform recon:

1. Identify layout variations (Case 0, Case 1, Case 2...)
2. Document HTML structure (screenshot + selectors)
3. Update `collector.py` with selectors
4. Test on 5-10 jobs
5. Enable in config once stable

See: `docs/RECON-TEMPLATE.md`

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

---

Built with Claude Code during Month 1 of 24-month tech progression.
