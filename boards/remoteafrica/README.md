# RemoteAfrica Board

Remote4Africa job board collector for the Job Search Automation Agent.

## Overview

This collector scrapes [remote4africa.com](https://remote4africa.com), a job board focused on remote opportunities for African talent. Unlike other boards in this repo, RemoteAfrica uses a **global job list** approach rather than keyword-based search.

## How It Works

### Collection Strategy

RemoteAfrica does **not** apply keyword filters during collection. The collector:

1. Visits `https://remote4africa.com/jobs` (and paginated variants `?page=N`)
2. Extracts all links matching `/jobs/[slug]` pattern
3. Visits each job detail page
4. Parses job data from JSON-LD `JobPosting` schema

**Important**: Keywords defined in `config/settings.yaml` are **ignored** during scraping. The collector fetches all available jobs from the global list and relies on post-run filtering to narrow results.

### Data Extraction

Jobs are extracted primarily from JSON-LD structured data embedded in detail pages. Fields include:

- Title, company, location
- Job type (Full-time, Part-time, Contract, etc.)
- Salary (when available)
- Date posted, expiration date
- Applicant location requirements
- Full job description

### Filtering

Since collection is not keyword-driven, use the post-run sorter to filter results:

```bash
cd boards/remoteafrica
python3 ../../shared/post_run_sorter.py --latest
```

Configure filtering rules in `config/settings.yaml` under `post_run`.

## Configuration

### Standard Config: `config/settings.yaml`

```yaml
search:
  job_boards:
    - remoteafrica  # MUST be set to remoteafrica
  max_pages: 2      # Pagination depth (0 = unlimited)
  max_results_per_search: 50
  keywords:         # These are IGNORED during collection
    - AI engineer
    - machine learning engineer

browser:
  headless: false   # Visible browser for debugging
```

### Headless Config: `config/settings.headless.yaml`

Use for automated/background runs:

```yaml
browser:
  headless: true
```

## Running the Collector

### Standard Run (Visible Browser)

```bash
./scripts/run_board.sh remoteafrica
```

### Headless Run (Background)

```bash
./scripts/run_board.sh remoteafrica config/settings.headless.yaml
```

## Output

Jobs are saved to:

- **JSON**: `boards/remoteafrica/output/jobs_TIMESTAMP.json`
- **Markdown**: `boards/remoteafrica/output/jobs_TIMESTAMP.md`

If `vault_sync` is enabled in config, jobs also sync to your Obsidian vault.

## Troubleshooting

### No Job Links Found

If the collector reports "No job links found", check debug artifacts:

- `boards/remoteafrica/output/debug_screenshot.png`
- `boards/remoteafrica/output/debug_page.html`

Common causes:
- Site structure changed (selectors need updating)
- Cloudflare captcha blocking the page
- Network/timeout issues

### Captcha Issues

If you hit a captcha during collection, the collector will:
1. Save debug screenshots with timestamps
2. Prompt for action (solve manually, abort, skip remaining fetches)

### Keywords Not Working

**This is expected.** RemoteAfrica collects from a global list. Use post-run filtering instead of relying on search keywords.

## Limitations

- **No keyword search**: Keywords in config are not applied during scraping
- **Single query only**: If multiple keywords are configured, only the first query runs
- **Relies on JSON-LD**: Jobs without structured data are skipped
- **No salary detail fetches**: RemoteAfrica jobs include salary data in JSON-LD, so detail fetches are typically unnecessary

## Maintenance

For technical details on the collector implementation, see:
- `src/collector.py` - Main collection logic
- `../../AUDIT-REMOTEAFRICA.md` - Full board audit (if available at repo root)

## Quick Reference

```bash
# Run standard collection
./scripts/run_board.sh remoteafrica

# Run headless
./scripts/run_board.sh remoteafrica config/settings.headless.yaml

# Filter results after collection
cd boards/remoteafrica
python3 ../../shared/post_run_sorter.py --latest

# Check debug artifacts
ls -lh boards/remoteafrica/output/debug_*
```
