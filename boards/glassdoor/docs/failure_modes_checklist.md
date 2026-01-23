# Failure Modes Checklist

- No job cards found
  - Check selectors for Glassdoor cards.
  - Confirm search URL still works in browser.
- Blocked by CAPTCHA / Cloudflare
  - Re-run `setup_session.py` and reduce detail fetch rate.
  - Disable headless mode.
- Salary extraction empty
  - Ensure `detail_salary_fetch` enabled and adjust selectors.
  - Validate JSON-LD presence on detail pages.
- Pagination stops early
  - Confirm next button selector and disabled state.
  - Increase `max_pages` or set to 0 for unlimited.
- Output QA warnings
  - Review `run_summary_*.json` for missing fields.
  - Update selectors in `src/collector.py` accordingly.
