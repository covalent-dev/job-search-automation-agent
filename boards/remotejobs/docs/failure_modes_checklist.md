# Failure Modes Checklist

- No job cards found
  - Confirm search URL still valid.
  - Update card selectors in `src/collector.py`.
- Missing location/description
  - Add selectors or detail-panel fetch.
- Pagination stops early
  - Check next button selectors or `page` parameter.
- Output QA warnings
  - Review `run_summary_*.json` and tune selectors.
