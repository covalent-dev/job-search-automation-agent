---
title: RemoteJobs Recon
project: job-search-automation-agent
status: draft
last-updated: 2026-01-19
---

# RemoteJobs Recon

## Goal

Confirm the fastest data path (API, DOM, or hybrid), then scaffold a minimal collector.

## Baseline Recon

- Entry point: https://www.remotejobs.io/
- Search URL (assumed): https://www.remotejobs.io/remote-jobs?search=<keyword>&location=<location>&page=<n>
- Pagination: `page` parameter (1-based).
- Stable ID: job detail links should include a path slug or ID.
- Data source: DOM list cards; detail page optional for salary/description.

## Data Mapping

- title: job card title link text.
- company: job card company name.
- location: job card location.
- url: job card link href (prefixed with https://www.remotejobs.io).
- date: job card posted/date tag.
- tags: job type and salary when available on the card.
- description: snippet on list view (detail page optional).

## Collector Scaffold

- Use Playwright to load search URL per keyword/location.
- Query job cards via multiple selectors.
- Extract title/company/location/link/salary/snippet/posted.
- Optional detail fetch uses generic salary/description selectors.
- Save JSON + Markdown + run summary + config snapshot.

## Risk Notes

- Selector churn due to class name hashing.
- Search URL parameters may differ; confirm in devtools.
- Detail fetch may trigger bot protections if rate is high.

## Integration Checklist

- Source name in config: `remotejobs`.
- Dedupe key: job link URL.
- Output writer schema: `Job` model fields.
- Smoke run with `config/settings.yaml`.
