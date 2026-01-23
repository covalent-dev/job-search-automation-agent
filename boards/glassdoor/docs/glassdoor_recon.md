---
title: Glassdoor Recon
project: job-search-automation-agent
status: draft
last-updated: 2026-01-18
---

# Glassdoor Recon

## Goal

Confirm the fastest data path (API, DOM, or hybrid), then scaffold a minimal collector.

## Baseline Recon

- Entry point: https://www.glassdoor.com/Job/index.htm
- Search URL (DOM): https://www.glassdoor.com/Job/jobs.htm?sc.keyword=<keyword>&locKeyword=<location>&p=<page>
- Pagination: `p` page number (1-based).
- Stable ID: job detail links typically include a Glassdoor listing slug or ID in the URL.
- Data source: DOM list cards; detail page optional for salary.

## Data Mapping

- title: job card title link text.
- company: job card company name.
- location: job card location.
- url: job card link href (prefixed with https://www.glassdoor.com).
- date: job card age/posted tag.
- tags: job type and salary when available on the card.
- description: snippet on list view (detail page optional).

## Collector Scaffold

- Use Playwright to load search URL per keyword/location.
- Query job cards via multiple selectors.
- Extract title/company/location/link/salary/snippet/posted.
- Optional detail fetch uses JSON-LD or salary selectors.
- Save JSON + Markdown + run summary + config snapshot.

## Risk Notes

- Login wall or CAPTCHA (Cloudflare).
- Selector churn due to class name hashing.
- Location requires a Glassdoor ID on some flows; fallback to locKeyword-only search.
- Detail fetch more likely to trigger blocks.

## Integration Checklist

- Source name in config: `glassdoor`.
- Dedupe key: job link URL.
- Output writer schema: `Job` model fields.
- Smoke run with `config/settings.yaml`.
