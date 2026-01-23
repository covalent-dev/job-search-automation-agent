# Glassdoor Runbook

## Setup

1. Install deps and Playwright.
2. Run `python src/setup_session.py --config config/settings.yaml`.
3. Solve any captcha and wait for results to load.

## Run

- Default (Glassdoor): `python src/main.py`
- Headless: `python src/main.py --config config/settings.headless.yaml`

## Expected Outputs

- JSON + Markdown in `output/`.
- `run_summary_*.json` with per-run stats and QA checks.
- `config_snapshot_*.yaml` for reproducibility.

## Recovery

- If blocked by captcha: rerun `setup_session.py` and slow down delays.
- If no jobs collected: adjust keywords/location or selectors in `src/collector.py`.
- If salary missing: enable `detail_salary_fetch` and reduce `detail_salary_max_per_query`.
