# Job Search Automation Agent v0.2.1

Scrapes jobs from multiple boards with proxy/captcha support, scores them with a local LLM, and syncs everything to Obsidian. Supports Indeed, Glassdoor, LinkedIn, RemoteJobs, and RemoteAfrica.

## Quick Start

```bash
# Run a specific board
cd boards/remotejobs
python -m src.collector

# With options
python -m src.collector --max-jobs 25 --headless

# Or via script
./scripts/run_board.sh remotejobs
```

## Board Status (as of 2026-01-30)

| Board | Headless | Proxy | Captcha | Descriptions | Dedupe | Status |
|-------|----------|-------|---------|--------------|--------|--------|
| RemoteJobs | ⚠️ Cloudflare | ✅ | N/A | ✅ 100% | ✅ slug | Working (headed) |
| RemoteAfrica | ✅ | ✅ | N/A | ✅ | ✅ slug | **Fully Working** |
| LinkedIn | ⚠️ | ✅ | ✅ reCAPTCHA | Partial | ✅ external_id | Working with proxy |
| Indeed | ❌ Cloudflare | ✅ | ✅ Turnstile | ❌ | ✅ jk | Needs stealth |
| Glassdoor | ❌ Cloudflare | ✅ | ✅ Turnstile | ❌ | ✅ URL | Needs stealth |

**Legend:**
- ✅ = Working
- ⚠️ = Works with workarounds
- ❌ = Blocked (Cloudflare detection)

## Structure

```
job-search-automation-agent/
├── boards/              # Board-specific collectors and configs
│   ├── indeed/
│   ├── glassdoor/
│   ├── linkedin/
│   ├── remotejobs/
│   └── remoteafrica/
├── shared/              # Shared core
│   ├── captcha_solver.py    # 2captcha integration
│   ├── config_loader.py     # Config with proxy/captcha support
│   ├── dedupe_store.py      # Cross-run deduplication
│   ├── ai_scorer.py         # Ollama LLM scoring
│   └── output_writer.py     # JSON/MD + Obsidian sync
├── scripts/             # Run scripts
└── requirements.txt
```

## Infrastructure

### Proxy (IPRoyal)
```bash
# Set env vars
export IPROYAL_USER="..."
export IPROYAL_PASS="..."
export IPROYAL_HOST="geo.iproyal.com"
export IPROYAL_PORT="12321"
```

Enable in board config:
```yaml
proxy:
  enabled: true
```

### Captcha Solver (2captcha)
```bash
export CAPTCHA_API_KEY="..."
```

Enable in board config:
```yaml
captcha:
  enabled: true
  policy: solve  # skip | abort | pause | solve
```

### FlareSolverr (Optional, Cloudflare JS challenges)
FlareSolverr can solve Cloudflare "Just a moment..." style JS challenges and return cookies + a user agent that the bot injects into the Playwright context.

Run FlareSolverr (example):
```bash
docker run --rm -p 8191:8191 flaresolverr/flaresolverr:latest
```

Enable in board config:
```yaml
flaresolverr:
  enabled: true
  url: "http://localhost:8191"
  timeout: 60
  use_proxy: true
```

### Stealth Mode
Both Indeed and Glassdoor collectors have built-in stealth infrastructure:
- Browser fingerprint spoofing
- navigator.webdriver override
- Human-like behavior simulation
- playwright-stealth integration

Enable in config:
```yaml
browser:
  use_stealth: true
```

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt
playwright install chromium

# 2. Set env vars (create .env or export)
export IPROYAL_USER="..."
export CAPTCHA_API_KEY="..."

# 3. First-time browser profile setup (per board)
export JOB_BOT_BOARD="linkedin"
python3 shared/setup_session.py

# 4. Run collection
cd boards/linkedin
python -m src.collector
```

## Configuration

Each board has `config/settings.yaml`:

```yaml
search:
  keywords:
    - "AI engineer"
    - "python developer"
  location: "Remote"
  max_results_per_search: 50
  max_pages: 10

browser:
  headless: true
  use_stealth: true

proxy:
  enabled: true

captcha:
  enabled: true
  policy: solve

output:
  vault_sync:
    enabled: true
    vault_path: ~/Taxman_Progression_v4/05_Knowledge_Base/Job-Market-Data/linkedin
```

## Deduplication

Cross-run dedupe prevents re-collecting the same jobs:
- **LinkedIn**: `external_id` (LinkedIn job ID)
- **Indeed**: `jk` (Indeed job key)
- **Glassdoor**: URL hash
- **RemoteJobs**: slug from URL
- **RemoteAfrica**: slug from URL

Dedupe files: `~/.job-search-automation/dedupe/<board>_seen.json`

## Output

- **JSON**: `boards/<board>/output/jobs_TIMESTAMP.json`
- **Markdown**: `boards/<board>/output/jobs_TIMESTAMP.md`
- **Obsidian**: Auto-synced if `vault_sync.enabled: true`

## Post-Run AI Scoring

```bash
cd boards/remotejobs
python3 ../../shared/post_run_sorter.py --latest --min-score 5
```

Options:
- `--latest` — Use most recent output file
- `--min-score N` — Filter to jobs scored N+
- `--top-n N` — Keep top N jobs only

## Architecture Notes

- Monorepo design scales to 30+ boards
- Each board isolates browser profile and config
- Shared code handles common logic (AI, output, dedupe)
- Collectors only implement site-specific selectors
- Playwright for browser automation with stealth patches

---

*Updated: 2026-01-30 | v0.2.1 — Proxy, Captcha, Dedupe infrastructure*
