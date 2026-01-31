"""
Job Collector - Playwright-based job listing collector
Handles browser automation and data extraction
"""

import json
import logging
import os
import random
import time
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
from models import Job, SearchQuery

logger = logging.getLogger(__name__)

SESSION_FILE = Path("config/session.json")
REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_NAME = REPO_ROOT.name
PROFILE_ROOT = Path.home() / ".job-search-automation"
# Match the profile naming used by setup_session.py
USER_DATA_DIR = PROFILE_ROOT / f"job-search-automation-{REPO_NAME}-profile"

DEFAULT_BLOCKED_FAIL_FAST_SECONDS = 25
DEFAULT_JOB_CARDS_WAIT_BUDGET_SECONDS = 12


class CaptchaAbort(Exception):
    """Raised when user opts to abort after captcha."""


@dataclass
class DetailPageData:
    """Holds all data extracted from a job detail page."""
    salary: Optional[str] = None
    job_type: Optional[str] = None
    company: Optional[str] = None
    description: Optional[str] = None
    date_posted: Optional[str] = None


class JobCollector:
    """Collects job listings using Playwright browser automation"""

    def __init__(self, config):
        self.config = config
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.detail_salary_page: Optional[Page] = None
        self.detail_description_page: Optional[Page] = None
        self.session_file = SESSION_FILE
        self.user_data_dir = USER_DATA_DIR
        self.max_retries = self.config.get_max_retries()
        self.detail_salary_cache: dict[str, tuple[Optional[str], Optional[str]]] = {}
        self.detail_description_cache: dict[str, Optional[str]] = {}
        self.detail_company_cache: dict[str, Optional[str]] = {}
        self.detail_date_cache: dict[str, Optional[str]] = {}
        self.detail_page_cache: dict[str, DetailPageData] = {}
        self.skip_detail_fetches = False
        self.detail_debug_saved = False
        self.detail_description_debug_saved = False
        self.captcha_debug_saved = False
        self.abort_requested = False
        self.total_jobs_collected = 0
        self.total_jobs_with_salary = 0
        self.detail_fetch_count_total = 0
        self.detail_description_count_total = 0
        self.first_captcha_fetch_count: Optional[int] = None
        self.captcha_events: list[dict] = []
        self.captcha_consecutive = 0
        self.captcha_backoff_base_seconds = 60
        self.captcha_backoff_max_seconds = 300
        self.current_query: Optional[str] = None
        self.current_board: Optional[str] = None
        self.jobs_checkpoint: List[Job] = []
        self.checkpoint_path = Path("output/progress_checkpoint.json")
        self.captcha_log_path = Path("output/captcha_log.json")

    def _random_delay(self) -> None:
        """Add human-like delay between actions"""
        min_delay = self.config.get_min_delay()
        max_delay = self.config.get_max_delay()
        delay = random.uniform(min_delay, max_delay)
        time.sleep(delay)

    def _blocked_fail_fast_seconds(self) -> int:
        value = None
        try:
            value = self.config.get("browser.blocked_fail_fast_seconds", None)
        except Exception:
            value = None
        if value is None:
            return DEFAULT_BLOCKED_FAIL_FAST_SECONDS
        try:
            return max(int(value), 5)
        except Exception:
            return DEFAULT_BLOCKED_FAIL_FAST_SECONDS

    def _job_cards_wait_budget_seconds(self) -> int:
        value = None
        try:
            value = self.config.get("browser.job_cards_wait_budget_seconds", None)
        except Exception:
            value = None
        if value is None:
            return DEFAULT_JOB_CARDS_WAIT_BUDGET_SECONDS
        try:
            return max(int(value), 3)
        except Exception:
            return DEFAULT_JOB_CARDS_WAIT_BUDGET_SECONDS

    def _save_debug_artifacts(self, prefix: str = "debug") -> None:
        try:
            Path("output").mkdir(parents=True, exist_ok=True)
        except Exception:
            return
        try:
            self.page.screenshot(path=f"output/{prefix}_screenshot.png")
        except Exception:
            pass
        try:
            Path(f"output/{prefix}_page.html").write_text(self.page.content(), encoding="utf-8")
        except Exception:
            pass

    def _record_block_event(self, details: dict, stage: str, target_url: str) -> None:
        try:
            Path("output").mkdir(parents=True, exist_ok=True)
            payload = {
                "timestamp": datetime.now().isoformat(),
                "stage": stage,
                "target_url": target_url,
                "page_url": (self.page.url if self.page else None),
                "details": details,
            }
            Path("output/block_event.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            logger.debug("Block event write failed", exc_info=True)

    def _fail_fast_if_blocked(self, stage: str, target_url: str) -> bool:
        if not self.page:
            return False
        detection = self._is_captcha_page(self.page)
        if not detection:
            return False

        self._save_debug_artifacts(prefix="debug")
        self._record_block_event(detection, stage=stage, target_url=target_url)

        reason = detection.get("reason")
        title = detection.get("title")
        url = detection.get("url")
        logger.error(
            "Blocked by captcha/Cloudflare (stage=%s, reason=%s, title=%s, url=%s, target=%s)",
            stage,
            reason,
            title,
            url,
            target_url,
        )
        print("\n   ✗ Blocked by Cloudflare/captcha challenge.")
        print(f"     Reason: {reason}")
        print("     Saved:  output/debug_screenshot.png, output/debug_page.html, output/block_event.json")
        print("     Remediation:")
        print("       - Run: JOB_BOT_BOARD=remotejobs python3 shared/setup_session.py (solve once, persistent profile)")
        print("       - Optional: set browser.use_stealth: true and/or enable a Playwright proxy")
        return True

    def _handle_remotejobs_error_page(self) -> bool:
        if self.current_board != "remotejobs":
            return False
        try:
            body = (self.page.inner_text("body") or "").lower()
        except Exception:
            body = ""
        if "apologies! something is wrong" not in body:
            return False

        logger.warning("RemoteJobs error page detected; attempting recovery")
        try:
            button = self.page.query_selector("text=Find Remote Jobs Now")
            if button:
                button.click()
                self._random_delay()
        except Exception:
            pass

        try:
            self.page.goto("https://www.remotejobs.io/remote-jobs", wait_until="domcontentloaded")
            self._random_delay()
        except Exception:
            return True

        try:
            keyword = self.current_query or ""
            input_selectors = [
                "input[placeholder*='keyword']",
                "input[placeholder*='title']",
                "input[type='text']",
            ]
            for selector in input_selectors:
                field = self.page.query_selector(selector)
                if field:
                    field.click()
                    field.fill(keyword)
                    try:
                        field.press("Enter")
                    except Exception:
                        pass
                    self._random_delay()
                    break
        except Exception:
            pass

        return True

    def _build_search_url(self, query: SearchQuery, page_index: int = 0) -> str:
        """Build search URL for job board"""
        keyword = query.keyword.replace(" ", "+")
        location = query.location.replace(" ", "+")
        job_board = (query.job_board or "").lower()

        if job_board == "remotejobs":
            page_number = page_index + 1
            base_url = f"https://www.remotejobs.io/remote-jobs?search={keyword}"
            if location:
                base_url += f"&location={location}"
            return f"{base_url}&page={page_number}"

        # Default: Indeed URL structure
        start = page_index * 10
        base_url = f"https://www.indeed.com/jobs?q={keyword}&l={location}"
        if start > 0:
            return f"{base_url}&start={start}"
        return base_url

    def _extract_text(self, element) -> str:
        if not element:
            return ""
        try:
            text = element.inner_text().strip()
        except Exception:
            text = ""
        if not text:
            try:
                text = (element.text_content() or "").strip()
            except Exception:
                text = ""
        return text

    def _first_text(self, root, selectors: list[str]) -> str:
        for selector in selectors:
            element = root.query_selector(selector)
            text = self._extract_text(element)
            if text:
                return text
        return ""

    def _first_element(self, root, selectors: list[str]):
        for selector in selectors:
            element = root.query_selector(selector)
            if element:
                return element
        return None

    def _serialize_job(self, job: Job) -> dict:
        if hasattr(job, "model_dump"):
            return job.model_dump()
        return job.dict()

    def _write_checkpoint(self, jobs: List[Job]) -> None:
        try:
            Path("output").mkdir(parents=True, exist_ok=True)
            payload = {
                "timestamp": datetime.now().isoformat(),
                "total_jobs": self.total_jobs_collected,
                "jobs_with_salary": self.total_jobs_with_salary,
                "current_query": self.current_query,
                "jobs": [self._serialize_job(job) for job in jobs],
            }
            self.checkpoint_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            logger.debug("Checkpoint write failed", exc_info=True)

    def _log_captcha(self, url: str) -> None:
        event = {
            "timestamp": datetime.now().isoformat(),
            "query": self.current_query,
            "job_number": self.total_jobs_collected + 1,
            "detail_fetch_count": self.detail_fetch_count_total,
            "url": url,
        }
        self.captcha_events.append(event)
        if self.first_captcha_fetch_count is None:
            self.first_captcha_fetch_count = self.detail_fetch_count_total
        try:
            Path("output").mkdir(parents=True, exist_ok=True)
            self.captcha_log_path.write_text(
                json.dumps(self.captcha_events, indent=2), encoding="utf-8"
            )
        except Exception:
            logger.debug("Captcha log write failed", exc_info=True)

    def _notify_captcha(self) -> None:
        try:
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    'display notification "Captcha detected during detail fetch. Action needed." with title "Job Bot"',
                ],
                check=False,
            )
        except Exception:
            logger.debug("Captcha notification failed", exc_info=True)

    def _handle_captcha_prompt(self, url: str) -> str:
        self._log_captcha(url)
        self._notify_captcha()
        print("\n⚠️  CAPTCHA detected during detail salary fetch.")
        print("Choose how to proceed:")
        print("  1) Solve manually (pause and resume)")
        print("  2) Abort run (save collected data)")
        print("  3) Skip remaining detail fetches (continue without salaries)")
        while True:
            choice = input("Enter 1, 2, or 3: ").strip()
            if choice == "1":
                print("\nSolve the captcha in the browser window, then press ENTER to continue.")
                input()
                return "retry"
            if choice == "2":
                print(
                    f"\nCollected {self.total_jobs_collected} jobs with "
                    f"{self.total_jobs_with_salary} salaries."
                )
                self.abort_requested = True
                return "abort"
            if choice == "3":
                print("\nSkipping remaining detail salary fetches for this run.")
                self.skip_detail_fetches = True
                return "skip"
            print("Invalid choice. Please enter 1, 2, or 3.")

    def _captcha_backoff(self) -> None:
        if self.captcha_consecutive <= 0:
            return
        delay_seconds = min(
            self.captcha_backoff_base_seconds * (2 ** (self.captcha_consecutive - 1)),
            self.captcha_backoff_max_seconds,
        )
        print(f"\n⏳ Backing off for {delay_seconds:.0f}s to reduce captcha triggers...")
        time.sleep(delay_seconds)

    def _classify_attribute_text(self, text: str) -> tuple[Optional[str], Optional[str]]:
        if not text:
            return None, None
        normalized = " ".join(text.split())
        lower = normalized.lower()

        job_type_map = {
            "full-time": "Full-time",
            "full_time": "Full-time",
            "part-time": "Part-time",
            "part_time": "Part-time",
            "contract": "Contract",
            "temporary": "Temporary",
            "internship": "Internship",
            "intern": "Internship",
            "seasonal": "Seasonal",
            "apprenticeship": "Apprenticeship",
        }
        job_types = []
        for key, label in job_type_map.items():
            if key in lower:
                job_types.append(label)

        job_type = ", ".join(job_types) if job_types else None

        salary = self._normalize_salary_text(normalized)

        return salary, job_type

    def _normalize_salary_unit(self, unit: Optional[str]) -> Optional[str]:
        if not unit:
            return None
        unit_lower = unit.strip().lower()
        if unit_lower in ("yr", "year"):
            return "year"
        if unit_lower in ("hr", "hour"):
            return "hour"
        return unit_lower

    def _normalize_salary_text(self, text: str) -> Optional[str]:
        if not text:
            return None
        pattern = re.compile(
            r"(?:\b(?:estimated|from|up to|starting at|starting from)\b\s+)?"
            r"([$£€])\s?(\d[\d,]*(?:\.\d+)?)"
            r"(?:\s*-\s*[$£€]?\s?(\d[\d,]*(?:\.\d+)?))?"
            r"\s*(?:an?|per)?\s*(hour|year|yr|month|week|day)\b",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            alt_pattern = re.compile(
                r"([$£€])\s?(\d[\d,]*(?:\.\d+)?)"
                r"(?:\s*-\s*[$£€]?\s?(\d[\d,]*(?:\.\d+)?))?"
                r"\s*(?:usd)?\s*(annually|annual|yearly|per year|per hour|hourly)",
                re.IGNORECASE,
            )
            alt_match = alt_pattern.search(text)
            if not alt_match:
                return None
            currency, min_raw, max_raw, unit_raw = alt_match.groups()
            unit_label = unit_raw.lower()
            if "hour" in unit_label:
                unit = "hour"
            else:
                unit = "year"
            def _format_amount(value_raw: str) -> str:
                try:
                    value = float(value_raw.replace(",", ""))
                except Exception:
                    return f"{currency}{value_raw}"
                if value.is_integer():
                    return f"{currency}{int(value):,}"
                return f"{currency}{value:,.2f}"
            min_text = _format_amount(min_raw)
            max_text = _format_amount(max_raw) if max_raw else None
            if max_text:
                salary = f"{min_text} - {max_text}"
            else:
                salary = min_text
            unit_norm = self._normalize_salary_unit(unit)
            if unit_norm:
                salary = f"{salary} per {unit_norm}"
            return salary
        currency, min_raw, max_raw, unit_raw = match.groups()
        unit = self._normalize_salary_unit(unit_raw)
        if not unit:
            return None

        def _format_amount(value_raw: str) -> str:
            try:
                value = float(value_raw.replace(",", ""))
            except Exception:
                return f"{currency}{value_raw}"
            if value.is_integer():
                return f"{currency}{int(value):,}"
            return f"{currency}{value:,.2f}"

        min_text = _format_amount(min_raw)
        max_text = _format_amount(max_raw) if max_raw else None
        article = "an" if unit == "hour" else "a"
        if max_text:
            return f"{min_text} - {max_text} {article} {unit}"
        return f"{min_text} {article} {unit}"

    def _normalize_job_type_value(self, value: str) -> Optional[str]:
        if not value:
            return None
        normalized = value.strip().replace("_", "-").lower()
        job_type_map = {
            "full-time": "Full-time",
            "part-time": "Part-time",
            "contract": "Contract",
            "temporary": "Temporary",
            "intern": "Internship",
            "internship": "Internship",
            "seasonal": "Seasonal",
            "apprenticeship": "Apprenticeship",
        }
        if normalized in job_type_map:
            return job_type_map[normalized]
        return normalized.replace("-", " ").title()

    def _format_salary(self, currency: Optional[str], min_value: Optional[float],
                       max_value: Optional[float], unit: Optional[str]) -> Optional[str]:
        if min_value is None and max_value is None:
            return None
        currency_symbol = "$" if currency == "USD" else (currency or "")
        if min_value is not None:
            min_text = f"{currency_symbol}{int(min_value):,}"
        else:
            min_text = None
        if max_value is not None:
            max_text = f"{currency_symbol}{int(max_value):,}"
        else:
            max_text = None
        if min_text and max_text:
            salary = f"{min_text} - {max_text}"
        else:
            salary = min_text or max_text
        unit_norm = self._normalize_salary_unit(unit)
        if unit_norm:
            article = "an" if unit_norm == "hour" else "a"
            salary = f"{salary} {article} {unit_norm}"
        return salary

    def _clean_company_name(self, name: Optional[str]) -> Optional[str]:
        if not name:
            return None
        cleaned = re.sub(r"\s+", " ", name).strip()
        if len(cleaned) < 2 or len(cleaned) > 100:
            return None
        lower = cleaned.lower()
        if lower in {"remotejobs", "remote jobs", "remotejobs.io"}:
            return None
        if "remotejobs.io" in lower or "remote jobs" == lower:
            return None
        if "http://" in lower or "https://" in lower:
            return None
        if re.search(r"\bemployee", lower):
            return None
        if not re.search(r"[a-zA-Z]", cleaned):
            return None
        return cleaned

    def _extract_company_name_from_value(self, value) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            return self._clean_company_name(value)
        if isinstance(value, dict):
            for key in ("name", "legalName", "companyName", "company_name"):
                candidate = value.get(key)
                if isinstance(candidate, str):
                    cleaned = self._clean_company_name(candidate)
                    if cleaned:
                        return cleaned
            return None
        if isinstance(value, list):
            for entry in value:
                found = self._extract_company_name_from_value(entry)
                if found:
                    return found
        return None

    def _find_company_name_in_data(self, data, max_depth: int = 6) -> Optional[str]:
        if max_depth <= 0 or data is None:
            return None
        if isinstance(data, dict):
            for key in ("companyName", "company_name", "company", "employer", "organization", "hiringOrganization"):
                if key in data:
                    found = self._extract_company_name_from_value(data.get(key))
                    if found:
                        return found
            for value in data.values():
                found = self._find_company_name_in_data(value, max_depth - 1)
                if found:
                    return found
        elif isinstance(data, list):
            for entry in data:
                found = self._find_company_name_in_data(entry, max_depth - 1)
                if found:
                    return found
        return None

    def _extract_company_from_json_ld(self, page: Page) -> Optional[str]:
        for script in page.query_selector_all("script[type='application/ld+json']"):
            raw = self._extract_text(script)
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                graph = item.get("@graph")
                if isinstance(graph, list):
                    items.extend([entry for entry in graph if isinstance(entry, dict)])
                found = self._find_company_name_in_data(item)
                if found:
                    return found
        return None

    def _extract_company_from_next_data(self, page: Page) -> Optional[str]:
        script = page.query_selector("script#__NEXT_DATA__")
        raw = self._extract_text(script)
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except Exception:
            return None
        return self._find_company_name_in_data(data, max_depth=7)

    def _extract_date_from_next_data(self, page: Page) -> Optional[str]:
        """Extract postedDate from __NEXT_DATA__ JSON (RemoteJobs uses Next.js)."""
        script = page.query_selector("script#__NEXT_DATA__")
        raw = self._extract_text(script)
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except Exception:
            return None
        # Path: props.pageProps.data.jobDetails.postedDate
        try:
            job_details = data.get("props", {}).get("pageProps", {}).get("data", {}).get("jobDetails", {})
            posted_date = job_details.get("postedDate")
            if posted_date:
                # Format: "2025-12-12T22:59:29Z" -> "2025-12-12"
                if "T" in posted_date:
                    return posted_date.split("T")[0]
                return posted_date
        except Exception:
            pass
        return None

    def _extract_company_from_dom(self, page: Page) -> Optional[str]:
        root = page.query_selector("main") or page.query_selector("article") or page
        selectors = [
            "[data-testid='company-name']",
            "[data-testid='companyName']",
            "[data-testid='company']",
            "[data-test='company-name']",
            ".company-name",
            ".companyName",
            ".company",
            "[class*='company']",
            "a[href*='/company/']",
            "a[href*='/companies/']",
            "a[href*='/employer/']",
            "a[href*='/employers/']",
        ]
        text = self._first_text(root, selectors)
        cleaned = self._clean_company_name(text)
        if cleaned:
            return cleaned
        meta_selectors = [
            "meta[name='author']",
            "meta[property='article:author']",
            "meta[name='company']",
        ]
        for selector in meta_selectors:
            meta = page.query_selector(selector)
            content = meta.get_attribute("content") if meta else ""
            cleaned = self._clean_company_name(content)
            if cleaned:
                return cleaned
        return None

    def _extract_company_from_title(self, page: Page) -> Optional[str]:
        try:
            title = (page.title() or "").strip()
        except Exception:
            return None
        if not title:
            return None
        match = re.search(r"\bat\s+([^|\-–—]+)", title, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            cleaned = self._clean_company_name(candidate)
            if cleaned:
                return cleaned
        if "|" in title:
            parts = [part.strip() for part in title.split("|") if part.strip()]
            if len(parts) >= 2:
                candidate = parts[-2]
                cleaned = self._clean_company_name(candidate)
                if cleaned:
                    return cleaned
        return None

    def _extract_company_from_detail_page(self, page: Page) -> Optional[str]:
        for extractor in (
            self._extract_company_from_next_data,
            self._extract_company_from_json_ld,
            self._extract_company_from_dom,
            self._extract_company_from_title,
        ):
            try:
                company = extractor(page)
            except Exception:
                company = None
            if company:
                return company
        return None

    def _extract_salary_from_json_ld(self, page: Page) -> tuple[Optional[str], Optional[str]]:
        salary = None
        job_type = None
        for script in page.query_selector_all("script[type='application/ld+json']"):
            raw = self._extract_text(script)
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                employment = item.get("employmentType")
                if employment and not job_type:
                    if isinstance(employment, list):
                        normalized_types = []
                        for entry in employment:
                            normalized = self._normalize_job_type_value(str(entry))
                            if normalized and normalized not in normalized_types:
                                normalized_types.append(normalized)
                        if normalized_types:
                            job_type = ", ".join(normalized_types)
                    else:
                        normalized = self._normalize_job_type_value(str(employment))
                        if normalized:
                            job_type = normalized
                base_salary = item.get("baseSalary")
                if not isinstance(base_salary, dict):
                    continue
                currency = base_salary.get("currency")
                value = base_salary.get("value", {})
                min_value = value.get("minValue")
                max_value = value.get("maxValue")
                unit = value.get("unitText")
                formatted = self._format_salary(currency, min_value, max_value, unit)
                if formatted and not salary:
                    salary = formatted
            if salary or job_type:
                break
        return salary, job_type

    def _is_captcha_page(self, page: Page) -> Optional[dict]:
        try:
            title = (page.title() or "").lower()
            url = (page.url or "").lower()
            title_markers = [
                "just a moment...",
                "attention required! | cloudflare",
            ]
            for marker in title_markers:
                if marker in title:
                    return {"reason": f"title:{marker}", "title": title, "url": url}

            url_markers = [
                "__cf_chl",
                "/cdn-cgi/",
                "challenges.cloudflare.com",
                "cf-challenge",
            ]
            for marker in url_markers:
                if marker in url:
                    return {"reason": f"url:{marker}", "title": title, "url": url}

            selector_markers = {
                "#cf-challenge-running": "selector:#cf-challenge-running",
                "form#challenge-form": "selector:form#challenge-form",
                "iframe[src*='challenges.cloudflare.com']": "selector:cloudflare-iframe",
                "iframe[src*='hcaptcha.com']": "selector:hcaptcha-iframe",
                "iframe[src*='recaptcha']": "selector:recaptcha-iframe",
                ".cf-turnstile": "selector:cf-turnstile",
                "[data-sitekey]": "selector:data-sitekey",
            }
            for selector, reason in selector_markers.items():
                if page.query_selector(selector):
                    return {"reason": reason, "title": title, "url": url}

            body = (page.inner_text("body") or "").lower()
            body_markers = [
                "cloudflare",
                "captcha",
                "verify you are human",
                "additional verification required",
            ]
            for marker in body_markers:
                if marker in body:
                    return {"reason": f"body:{marker}", "title": title, "url": url}
            return None
        except Exception:
            return None

    def _fetch_detail_page(self, url: str) -> DetailPageData:
        """Single consolidated detail page fetch that extracts all available data."""
        if not self.context or not url:
            return DetailPageData()
        if self.skip_detail_fetches:
            return DetailPageData()

        if url in self.detail_page_cache:
            return self.detail_page_cache[url]

        timeout_ms = self.config.get_detail_salary_timeout() * 1000
        retries = self.config.get_detail_salary_retries()
        delay_min = self.config.get_detail_salary_delay_min()
        delay_max = self.config.get_detail_salary_delay_max()
        job_board = (self.current_board or "").lower()

        if job_board == "remotejobs":
            salary_selectors = [
                ".salary", ".job-salary", ".jobSalary",
                "[class*='salary']", "[class*='Salary']",
                "[class*='pay']", "[class*='Pay']",
                "[class*='compensation']", "[class*='Compensation']",
                "[data-testid='salary']", "[data-testid='jobSalary']",
                "[data-test='salary']",
                "section[class*='salary']", "div[class*='salary']",
            ]
            detail_section_selectors = [
                "#jobDescriptionText", ".jobsearch-JobComponent-description",
                "#jobDetailsSection", "[data-testid='jobDetailsSection']",
                "[data-testid='jobDescriptionText']",
                "div.job-description", "div.jobDescription",
                "[class*='job-description']", "[class*='jobDescription']",
                "article", "main",
            ]
            description_selectors = [
                "#jobDescriptionText", "[data-testid='jobDescriptionText']",
                ".jobsearch-jobDescriptionText", ".jobsearch-JobComponent-description",
                "#jobDetailsSection", "[data-testid='jobDetailsSection']",
                "div.job-description", ".job-description", ".jobDescription",
                "div[class*='job-description']", "div[class*='jobDescription']",
                "div[class*='JobDescription']",
            ]
        else:
            salary_selectors = [
                "[data-testid='jobsearch-JobInfoHeader-salary']",
                "[data-testid='salary-snippet']",
                "[data-testid='salaryInfoAndJobType']",
                "#salaryInfoAndJobType",
                "[data-testid='jobMetadataHeader']",
                ".jobsearch-JobMetadataHeader-item",
                ".jobsearch-JobMetadataHeader-iconLabel",
                ".salary-snippet",
            ]
            detail_section_selectors = [
                "section[aria-label='Job details']",
                "[data-testid='jobDetailsSection']",
                "#jobDetailsSection",
            ]
            description_selectors = [
                "#jobDescriptionText", "[data-testid='jobDescriptionText']",
                ".jobsearch-jobDescriptionText",
                "#jobDetailsSection", "[data-testid='jobDetailsSection']",
            ]

        data = DetailPageData()
        attempt = 0

        while attempt < retries:
            try:
                attempt += 1
                if self.detail_salary_page is not None and self.detail_salary_page.is_closed():
                    self.detail_salary_page = None
                if self.detail_salary_page is None:
                    self.detail_salary_page = self.context.new_page()
                    self.detail_salary_page.set_default_timeout(timeout_ms)
                    self.detail_salary_page.set_default_navigation_timeout(timeout_ms)
                detail_page = self.detail_salary_page

                if delay_max > 0:
                    delay_seconds = random.uniform(delay_min, delay_max)
                    time.sleep(delay_seconds)

                detail_page.goto(url, wait_until="domcontentloaded")

                if job_board != "remotejobs":
                    try:
                        detail_page.wait_for_url("**/viewjob?jk=**", timeout=3000)
                    except Exception:
                        pass

                try:
                    wait_timeout = 1500 if job_board == "remotejobs" else 3000
                    detail_page.wait_for_selector(", ".join(detail_section_selectors), timeout=wait_timeout)
                except Exception:
                    pass

                if job_board != "remotejobs":
                    for selector in salary_selectors + detail_section_selectors:
                        try:
                            detail_page.wait_for_selector(selector, timeout=2000)
                            break
                        except Exception:
                            continue

                captcha_detection = self._is_captcha_page(detail_page)
                if captcha_detection:
                    self.captcha_consecutive += 1
                    logger.warning(
                        "Detail page fetch blocked by captcha (reason=%s, title=%s, url=%s)",
                        captcha_detection["reason"],
                        captcha_detection["title"],
                        captcha_detection["url"],
                    )
                    self._captcha_backoff()
                    if not self.captcha_debug_saved:
                        try:
                            Path("output").mkdir(parents=True, exist_ok=True)
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            detail_page.screenshot(path=f"output/detail_captcha_{timestamp}.png")
                            Path(f"output/detail_captcha_{timestamp}.html").write_text(
                                detail_page.content(), encoding="utf-8"
                            )
                            self.captcha_debug_saved = True
                        except Exception:
                            pass
                    if self.config.is_headless() or not sys.stdin.isatty():
                        logger.warning("Non-interactive run; skipping remaining detail fetches after captcha")
                        self.skip_detail_fetches = True
                        return DetailPageData()
                    action = self._handle_captcha_prompt(url)
                    if action == "abort":
                        raise CaptchaAbort("User requested abort after captcha")
                    if action == "skip":
                        return DetailPageData()
                    if action == "retry":
                        self.detail_salary_page = None
                        attempt = max(attempt - 1, 0)
                        continue
                else:
                    self.captcha_consecutive = 0

                # Extract salary and job_type from JSON-LD
                if self.config.is_detail_salary_enabled():
                    json_salary, json_job_type = self._extract_salary_from_json_ld(detail_page)
                    if json_salary:
                        data.salary = json_salary
                    if json_job_type:
                        data.job_type = json_job_type

                    # Also try DOM-based extraction
                    text_chunks = []
                    for selector in salary_selectors:
                        for element in detail_page.query_selector_all(selector):
                            text = self._extract_text(element)
                            if text:
                                text_chunks.append(text)
                    for selector in detail_section_selectors:
                        for element in detail_page.query_selector_all(selector):
                            text = self._extract_text(element)
                            if text:
                                text_chunks.append(text)
                    for text in text_chunks:
                        found_salary, found_job_type = self._classify_attribute_text(text)
                        if found_salary and not data.salary:
                            data.salary = found_salary
                        if found_job_type and not data.job_type:
                            data.job_type = found_job_type
                        if data.salary and data.job_type:
                            break

                # Extract company
                if job_board == "remotejobs":
                    detail_company = self._extract_company_from_detail_page(detail_page)
                    if detail_company:
                        data.company = detail_company

                # Extract date_posted from __NEXT_DATA__ (RemoteJobs only)
                if job_board == "remotejobs":
                    detail_date = self._extract_date_from_next_data(detail_page)
                    if detail_date:
                        data.date_posted = detail_date

                # Extract description
                if self.config.is_detail_description_enabled():
                    for selector in description_selectors:
                        elem = detail_page.query_selector(selector)
                        text = self._extract_text(elem)
                        if text and (not data.description or len(text) > len(data.description)):
                            data.description = text

                # Debug output if no salary found
                if self.config.is_detail_salary_enabled() and not data.salary and not self.detail_debug_saved:
                    try:
                        Path("output").mkdir(parents=True, exist_ok=True)
                        detail_page.screenshot(path="output/detail_debug.png")
                        Path("output/detail_debug.html").write_text(
                            detail_page.content(), encoding="utf-8"
                        )
                        self.detail_debug_saved = True
                    except Exception:
                        pass

                # Debug output if no description found
                if self.config.is_detail_description_enabled() and not data.description and not self.detail_description_debug_saved:
                    try:
                        Path("output").mkdir(parents=True, exist_ok=True)
                        detail_page.screenshot(path="output/detail_description_debug.png")
                        Path("output/detail_description_debug.html").write_text(
                            detail_page.content(), encoding="utf-8"
                        )
                        self.detail_description_debug_saved = True
                    except Exception:
                        pass

                # Successfully loaded page - break retry loop
                break

            except Exception as exc:
                if isinstance(exc, CaptchaAbort):
                    raise
                if "Target page, context or browser has been closed" in str(exc):
                    self.detail_salary_page = None
                logger.warning("Detail page fetch failed (attempt %s/%s): %s", attempt, retries, exc)
                self._random_delay()

        # Cache individual fields for backward compatibility
        self.detail_salary_cache[url] = (data.salary, data.job_type)
        self.detail_description_cache[url] = data.description
        if data.company:
            self.detail_company_cache[url] = data.company
        if data.date_posted:
            self.detail_date_cache[url] = data.date_posted

        self.detail_page_cache[url] = data
        return data

    def _fetch_detail_salary(self, url: str) -> tuple[Optional[str], Optional[str]]:
        """Wrapper for backward compatibility - uses unified _fetch_detail_page."""
        if url in self.detail_salary_cache:
            return self.detail_salary_cache[url]
        data = self._fetch_detail_page(url)
        return data.salary, data.job_type

    def _fetch_detail_company(self, url: str) -> Optional[str]:
        """Wrapper for backward compatibility - uses unified _fetch_detail_page."""
        if url in self.detail_company_cache:
            return self.detail_company_cache[url]
        job_board = (self.current_board or "").lower()
        if job_board != "remotejobs":
            return None
        data = self._fetch_detail_page(url)
        return data.company

    def _fetch_detail_description(self, url: str) -> Optional[str]:
        """Wrapper for backward compatibility - uses unified _fetch_detail_page."""
        if url in self.detail_description_cache:
            return self.detail_description_cache[url]
        data = self._fetch_detail_page(url)
        return data.description

    def _fetch_detail_date(self, url: str) -> Optional[str]:
        """Wrapper to get date_posted from detail page (RemoteJobs only)."""
        if url in self.detail_date_cache:
            return self.detail_date_cache[url]
        job_board = (self.current_board or "").lower()
        if job_board != "remotejobs":
            return None
        data = self._fetch_detail_page(url)
        return data.date_posted

    def _safe_goto(self, url: str) -> bool:
        """Navigate with retry for flaky pages."""
        for attempt in range(1, self.max_retries + 1):
            try:
                timeout_ms = self.config.get_navigation_timeout()
                if (self.current_board or "").lower() == "remotejobs":
                    timeout_ms = min(timeout_ms, self._blocked_fail_fast_seconds() * 1000)
                self.page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                return True
            except Exception as exc:
                logger.warning("Navigation failed (attempt %s/%s): %s", attempt, self.max_retries, exc)
                self._random_delay()
        return False

    def _has_next_page(self) -> bool:
        """Check if a next page control exists and is enabled."""
        job_board = (self.current_board or "").lower()
        if job_board == "remotejobs":
            selectors = [
                # Semantic rel attribute
                "a[rel='next']",
                # Aria labels
                "a[aria-label='Next']",
                "a[aria-label='Next page']",
                "a[aria-label='Next Page']",
                "button[aria-label='Next']",
                "button[aria-label='Next page']",
                "button[aria-label='Next Page']",
                # Class-based patterns
                "a.pagination-next",
                "a.next",
                "button.next",
                "[class*='pagination'] a[class*='next']",
                "[class*='Pagination'] a[class*='next']",
                "[class*='pagination'] button[class*='next']",
                "[class*='pager'] a[class*='next']",
                # Data attribute patterns
                "a[data-testid='pagination-next']",
                "button[data-testid='pagination-next']",
                "[data-testid='next-page']",
                # Text-based patterns (use :has-text carefully)
                "a:has-text('Next')",
                "button:has-text('Next')",
                "a:has-text('›')",
                "button:has-text('›')",
                "a:has-text('»')",
                "button:has-text('»')",
            ]
        else:
            selectors = [
                "a[aria-label='Next Page']",
                "a[aria-label='Next']",
                "a[aria-label='Next page']",
            ]
        for selector in selectors:
            element = self.page.query_selector(selector)
            if not element:
                continue
            aria_disabled = (element.get_attribute("aria-disabled") or "").lower()
            disabled_attr = element.get_attribute("disabled")
            if aria_disabled in ("true", "disabled") or disabled_attr is not None:
                return False
            return True
        return False

    def start_browser(self) -> None:
        """Initialize Playwright browser with persistent profile"""
        logger.info("Starting browser...")
        self.playwright = sync_playwright().start()
        channel = self.config.get_browser_channel() or None
        executable_path = self.config.get_browser_executable_path() or None
        launch_timeout = self.config.get_launch_timeout()
        proxy = None

        def _looks_like_proxy_failure(message: str) -> bool:
            msg = (message or "").lower()
            markers = (
                "err_proxy_connection_failed",
                "err_tunnel_connection_failed",
                "proxy authentication",
                "authentication required",
                "proxy",
                "407",
            )
            return any(marker in msg for marker in markers)

        try:
            proxy = self.config.get_playwright_proxy()
        except Exception as exc:
            logger.error("Proxy configuration error: %s", exc)
            raise

        if proxy:
            logger.info("Proxy enabled: %s", proxy.get("server"))

        if executable_path and not Path(executable_path).exists():
            logger.warning("Browser executable not found: %s", executable_path)
            executable_path = None

        stealth_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-site-isolation-trials",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-accelerated-2d-canvas",
            "--disable-gpu",
            "--window-size=1920,1080",
            "--start-maximized",
            "--disable-infobars",
            "--disable-extensions",
            "--disable-plugins-discovery",
            "--disable-background-networking",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-breakpad",
            "--disable-component-extensions-with-background-pages",
            "--disable-default-apps",
            "--disable-features=TranslateUI",
            "--disable-hang-monitor",
            "--disable-ipc-flooding-protection",
            "--disable-popup-blocking",
            "--disable-prompt-on-repost",
            "--disable-renderer-backgrounding",
            "--disable-sync",
            "--force-color-profile=srgb",
            "--metrics-recording-only",
            "--no-first-run",
            "--password-store=basic",
            "--use-mock-keychain",
        ]

        # Check if persistent profile exists (preferred method)
        if self.user_data_dir.exists():
            logger.info(f"Using persistent profile: {self.user_data_dir}")
            launch_kwargs = dict(
                user_data_dir=str(self.user_data_dir),
                headless=self.config.is_headless(),
                viewport={"width": 1920, "height": 1080},
                args=stealth_args,
                channel=channel,
                executable_path=executable_path,
                timeout=launch_timeout,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                locale="en-US",
                timezone_id="America/New_York",
            )
            if proxy:
                launch_kwargs["proxy"] = proxy
            try:
                self.context = self.playwright.chromium.launch_persistent_context(**launch_kwargs)
            except Exception as exc:
                if proxy and _looks_like_proxy_failure(str(exc)):
                    logger.error(
                        "Proxy connection/auth failed for %s. Check credentials and connectivity.",
                        proxy.get("server"),
                    )
                raise
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        else:
            # Fallback to session file or new context
            logger.info("No persistent profile found, using regular context")
            launch_kwargs = dict(
                headless=self.config.is_headless(),
                args=stealth_args,
                channel=channel,
                executable_path=executable_path,
                timeout=launch_timeout,
            )
            if proxy:
                launch_kwargs["proxy"] = proxy
            try:
                self.browser = self.playwright.chromium.launch(**launch_kwargs)
            except Exception as exc:
                if proxy and _looks_like_proxy_failure(str(exc)):
                    logger.error(
                        "Proxy connection/auth failed for %s. Check credentials and connectivity.",
                        proxy.get("server"),
                    )
                raise

            if self.session_file.exists():
                logger.info(f"Loading session from {self.session_file}")
                context_kwargs = dict(
                    storage_state=str(self.session_file),
                    viewport={"width": 1920, "height": 1080},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                    locale="en-US",
                    timezone_id="America/New_York",
                )
                if proxy:
                    context_kwargs["proxy"] = proxy
                self.context = self.browser.new_context(**context_kwargs)
            else:
                logger.warning("No session found - run setup_session.py first!")
                context_kwargs = dict(
                    viewport={"width": 1920, "height": 1080},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                    locale="en-US",
                    timezone_id="America/New_York",
                )
                if proxy:
                    context_kwargs["proxy"] = proxy
                self.context = self.browser.new_context(**context_kwargs)

            self.page = self.context.new_page()

        self.page.set_default_timeout(self.config.get_page_timeout())
        self.page.set_default_navigation_timeout(self.config.get_navigation_timeout())

        if self.config.use_stealth():
            try:
                from playwright_stealth.stealth import Stealth
                Stealth().apply_stealth_sync(self.page)
                logger.info("Playwright stealth enabled")
            except Exception as exc:
                logger.warning("Failed to enable stealth mode: %s", exc)

        logger.info("Browser started successfully")

    def stop_browser(self) -> None:
        """Clean up browser resources"""
        try:
            if self.detail_salary_page:
                self.detail_salary_page.close()
        except Exception:
            logger.debug("Detail salary page close failed", exc_info=True)
        try:
            if self.detail_description_page:
                self.detail_description_page.close()
        except Exception:
            logger.debug("Detail description page close failed", exc_info=True)
        try:
            if self.context:
                self.context.close()
        except Exception:
            logger.debug("Browser context close failed", exc_info=True)
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            logger.debug("Browser close failed", exc_info=True)
        try:
            if self.playwright:
                self.playwright.stop()
        except Exception:
            logger.debug("Playwright stop failed", exc_info=True)
        logger.info("Browser closed")

    def _get_job_cards(self, job_board: str) -> list:
        if job_board == "remotejobs":
            if self._is_captcha_page(self.page):
                return []
        selectors = []
        if job_board == "remotejobs":
            selectors = [
                # Primary: ID-based selectors (original structure)
                "div[id^='job-card-wrapper-']",
                "a[id^='job-card-title-']",
                # Semantic HTML patterns
                "article[data-job-id]",
                "article[data-id]",
                "li[data-job-id]",
                "li[data-id]",
                "div[data-job-id]",
                "div[data-id]",
                # Common React job board patterns
                "article.job",
                "article.job-card",
                "article.JobCard",
                "article[class*='job']",
                "article[class*='Job']",
                # Div-based cards
                "div.job-card",
                "div.JobCard",
                "div[class*='JobCard']",
                "div[class*='jobCard']",
                "div[class*='job-card']",
                "div.job",
                # List-based structures
                "li.job",
                "li.job-card",
                "li[class*='job']",
                "li[class*='Job']",
                # Link-based cards
                "a.job-card",
                "a[class*='job-card']",
                "a[class*='JobCard']",
                # Data attribute patterns
                "div[data-testid='job-card']",
                "div[data-testid='jobCard']",
                "div[data-testid='job-listing']",
                "div[data-testid='jobListing']",
                "[data-testid*='job']",
                # Section-based patterns
                "section[class*='job'] > div",
                "section[class*='Job'] > div",
                "main[class*='job'] article",
                "main[class*='Job'] article",
                # Grid/list container children
                "ul[class*='job'] > li",
                "ul[class*='Job'] > li",
                "div[class*='jobs'] > div",
                "div[class*='Jobs'] > div",
                "div[class*='listing'] > div",
                "div[class*='Listing'] > div",
                # Generic fallbacks
                "div[class*='card'][class*='job']",
                "div[class*='Card'][class*='Job']",
            ]
        else:
            selectors = [
                ".job_seen_beacon",
                ".jobsearch-ResultsList > li",
                "[data-testid='jobListing']",
                ".resultContent",
                ".tapItem",
            ]

        job_cards = []
        budget_seconds = self._job_cards_wait_budget_seconds() if job_board == "remotejobs" else 25
        budget_deadline = time.monotonic() + budget_seconds
        for selector in selectors:
            remaining_ms = int(max(0.0, budget_deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                break
            try:
                self.page.wait_for_selector(selector, timeout=min(1000, remaining_ms))
                job_cards = self.page.query_selector_all(selector)
                if job_cards:
                    logger.info("Found jobs using selector: %s", selector)
                    break
            except Exception:
                continue

        return job_cards

    def collect_jobs(self, query: SearchQuery, global_seen_links: set[str] | None = None) -> List[Job]:
        """Collect jobs for a single search query"""
        jobs = []
        seen_links = set()
        max_pages = self.config.get_max_pages()
        unlimited_pages = max_pages <= 0
        max_detail_fetches = self.config.get_detail_salary_max_per_query()
        unlimited_detail_fetches = max_detail_fetches <= 0
        detail_fetches = 0
        max_detail_description_fetches = self.config.get_detail_description_max_per_query()
        unlimited_detail_description_fetches = max_detail_description_fetches <= 0
        detail_description_fetches = 0

        last_first_link = None
        self.current_query = str(query)
        self.current_board = (query.job_board or "").lower()
        page_index = 0
        while True:
            if not unlimited_pages and page_index >= max_pages:
                break
            url = self._build_search_url(query, page_index=page_index)
            if unlimited_pages:
                page_label = f" (page {page_index + 1}/∞)"
            else:
                page_label = f" (page {page_index + 1}/{max_pages})" if max_pages > 1 else ""

            logger.info("Searching: %s%s", query, page_label)
            if hasattr(query, "index") and hasattr(query, "total"):
                print(f"\n🔍 Query {query.index}/{query.total}: {query}{page_label}")
            else:
                print(f"\n🔍 Searching: {query}{page_label}")

            try:
                # Navigate to search results
                if not self._safe_goto(url):
                    logger.warning("Failed to load search page after retries")
                    print("   ✗ Failed to load search page")
                    break
                self._random_delay()

                if self._handle_remotejobs_error_page():
                    self._random_delay()

                if self._fail_fast_if_blocked(stage="search-results", target_url=url):
                    break

                job_cards = self._get_job_cards(self.current_board)

                if not job_cards:
                    # Debug: save screenshot and HTML
                    self._save_debug_artifacts(prefix="debug")
                    logger.warning("No job cards found with any selector")
                    print("   ⚠️  No job cards found - saved debug screenshot")
                    break

                if self.current_board != "remotejobs":
                    try:
                        self.page.wait_for_selector(".job-snippet", timeout=3000)
                    except Exception:
                        pass

                logger.info("Found %s job cards", len(job_cards))
                print(f"   Found {len(job_cards)} listings")
                remaining_cap = query.max_results - len(jobs) if query.max_results > 0 else len(job_cards)
                progress_total = min(len(job_cards), remaining_cap) if remaining_cap > 0 else len(job_cards)

                added_this_page = 0
                first_link = None
                for i, card in enumerate(job_cards):
                    if query.max_results > 0 and len(jobs) >= query.max_results:
                        break
                    if progress_total > 0:
                        progress_current = min(i + 1, progress_total)
                        print(f"\r   Progress: {progress_current}/{progress_total}", end="", flush=True)
                    try:
                        job = self._extract_job_from_card(card)
                        link = str(job.link) if job and job.link else None
                        if (
                            job
                            and link
                            and link not in seen_links
                            and (global_seen_links is None or link not in global_seen_links)
                        ):
                            seen_links.add(link)
                            if global_seen_links is not None:
                                global_seen_links.add(link)
                            if (
                        self.config.is_detail_salary_enabled()
                        and not job.salary
                        and job.link
                        and not self.skip_detail_fetches
                        and (unlimited_detail_fetches or detail_fetches < max_detail_fetches)
                    ):
                                if unlimited_detail_fetches:
                                    fetch_label = f"{detail_fetches + 1}/∞"
                                else:
                                    fetch_label = f"{detail_fetches + 1}/{max_detail_fetches}"
                                self.detail_fetch_count_total += 1
                                print(f"\r   Detail salary: {fetch_label}", end="", flush=True)
                                logger.info(
                                    "Detail salary fetch %s: %s",
                                    fetch_label,
                                    job.link,
                                )
                                detail_salary, detail_job_type = self._fetch_detail_salary(str(job.link))
                                print("")
                                if detail_salary:
                                    job.salary = detail_salary
                                if detail_job_type:
                                    job.job_type = detail_job_type
                                detail_fetches += 1

                            if (
                                self.config.is_detail_description_enabled()
                                and job.link
                                and (unlimited_detail_description_fetches or detail_description_fetches < max_detail_description_fetches)
                            ):
                                if unlimited_detail_description_fetches:
                                    fetch_label = f"{detail_description_fetches + 1}/∞"
                                else:
                                    fetch_label = f"{detail_description_fetches + 1}/{max_detail_description_fetches}"
                                self.detail_description_count_total += 1
                                print(f"\r   Detail description: {fetch_label}", end="", flush=True)
                                logger.info(
                                    "Detail description fetch %s: %s",
                                    fetch_label,
                                    job.link,
                                )
                                detail_description = self._fetch_detail_description(str(job.link))
                                print("")
                                if detail_description:
                                    job.description_full = detail_description
                                detail_description_fetches += 1

                            if (
                                self.current_board == "remotejobs"
                                and job.link
                                and job.company == "Unknown Company"
                                and self.config.is_detail_company_enabled()
                                and not self.skip_detail_fetches
                                and (unlimited_detail_fetches or detail_fetches < max_detail_fetches)
                            ):
                                detail_company = self.detail_company_cache.get(str(job.link))
                                if not detail_company:
                                    if unlimited_detail_fetches:
                                        fetch_label = f"{detail_fetches + 1}/∞"
                                    else:
                                        fetch_label = f"{detail_fetches + 1}/{max_detail_fetches}"
                                    self.detail_fetch_count_total += 1
                                    print(f"\r   Detail company: {fetch_label}", end="", flush=True)
                                    logger.info(
                                        "Detail company fetch %s: %s",
                                        fetch_label,
                                        job.link,
                                    )
                                    detail_company = self._fetch_detail_company(str(job.link))
                                    print("")
                                    detail_fetches += 1
                                if detail_company:
                                    job.company = detail_company

                            if self.current_board == "remotejobs" and job.company == "Unknown Company":
                                cached_company = self.detail_company_cache.get(str(job.link))
                                if cached_company:
                                    job.company = cached_company

                            # Populate date_posted from cache (extracted during detail page fetch)
                            if self.current_board == "remotejobs" and not job.date_posted:
                                cached_date = self.detail_date_cache.get(str(job.link))
                                if cached_date:
                                    job.date_posted = cached_date

                            jobs.append(job)
                            self.total_jobs_collected += 1
                            if job.salary:
                                self.total_jobs_with_salary += 1
                            self.jobs_checkpoint.append(job)
                            if self.total_jobs_collected % 25 == 0:
                                self._write_checkpoint(self.jobs_checkpoint)
                            added_this_page += 1
                            logger.debug("Extracted: %s at %s", job.title, job.company)
                        if first_link is None and link:
                            first_link = link
                    except Exception as e:
                        logger.warning("Failed to extract job %s: %s", i, e)
                        continue

                    # Small delay between extractions
                    if i % 5 == 0:
                        self._random_delay()

                if progress_total > 0:
                    print("")
                print(f"   ✓ Collected {len(jobs)} jobs")

                if added_this_page == 0:
                    logger.info("No new jobs added on page %s; stopping pagination", page_index + 1)
                    break

                if first_link and last_first_link and first_link == last_first_link:
                    logger.info("First result repeated on page %s; stopping pagination", page_index + 1)
                    break
                if first_link:
                    last_first_link = first_link

            except CaptchaAbort:
                raise
            except KeyboardInterrupt:
                logger.warning("Interrupted during collection; returning partial results for query")
                print("   ⚠️  Interrupted - returning partial results")
                break
            except Exception as e:
                logger.error("Error collecting jobs: %s", e)
                print(f"   ✗ Error: {e}")
                break

            if not self._has_next_page():
                logger.info("No next page control found; stopping pagination")
                break

            if query.max_results > 0 and len(jobs) >= query.max_results:
                break

            page_index += 1

        return jobs

    def _extract_job_from_card(self, card) -> Optional[Job]:
        """Extract job data from a single job card element"""
        job_board = (self.current_board or "").lower()
        if job_board == "remotejobs":
            return self._extract_job_from_card_remotejobs(card)
        return self._extract_job_from_card_indeed(card)

    def _extract_job_from_card_indeed(self, card) -> Optional[Job]:
        try:
            title = self._first_text(card, ["h2.jobTitle span", "h2.jobTitle a"])
            title = title or "Unknown Title"

            company = self._first_text(card, ["[data-testid='company-name']"])
            company = company or "Unknown Company"

            location = self._first_text(card, ["[data-testid='text-location']"])
            location = location or "Unknown Location"

            link_elem = self._first_element(card, ["h2.jobTitle a"])
            href = link_elem.get_attribute("href") if link_elem else ""
            if href and not href.startswith("http"):
                href = f"https://www.indeed.com{href}"
            if not href:
                return None

            salary = None
            job_type = None
            attribute_elems = card.query_selector_all("[data-testid='attribute_snippet_testid']")
            for elem in attribute_elems:
                attr_text = self._extract_text(elem)
                if not attr_text:
                    continue
                attr_salary, attr_job_type = self._classify_attribute_text(attr_text)
                if attr_salary and not salary:
                    salary = attr_salary
                if attr_job_type and not job_type:
                    job_type = attr_job_type
                if salary and job_type:
                    break

            description = self._first_text(card, [".job-snippet"])

            date_posted = self._first_text(card, [".date"])

            return Job(
                title=title.strip(),
                company=company.strip(),
                location=location.strip(),
                link=href,
                salary=salary.strip() if salary else None,
                job_type=job_type.strip() if job_type else None,
                description=description.strip(),
                date_posted=date_posted.strip() if date_posted else None,
                source="indeed",
            )

        except Exception as e:
            logger.warning(f"Extraction error: {e}")
            return None

    def _extract_job_from_card_remotejobs(self, card) -> Optional[Job]:
        try:
            title = self._first_text(
                card,
                [
                    # Original ID-based selector
                    "a[id^='job-card-title-']",
                    # Standard heading patterns
                    "h1 a",
                    "h2 a",
                    "h3 a",
                    "h1",
                    "h2",
                    "h3",
                    # Data attribute patterns
                    "a[data-testid='job-title']",
                    "[data-testid='job-title']",
                    "[data-testid='jobTitle']",
                    "[data-test='job-title']",
                    # Class-based patterns
                    "a.job-title",
                    ".job-title",
                    ".jobTitle",
                    "[class*='jobTitle']",
                    "[class*='job-title']",
                    "[class*='JobTitle']",
                    "a[class*='title']",
                    # Semantic link (last resort)
                    "a[href*='/job/']",
                    "a[href*='/jobs/']",
                    "a",
                ],
            )
            title = title or "Unknown Title"

            # NOTE: RemoteJobs listing cards do not typically contain the company name.
            # It usually requires a detail page fetch. This extraction is a fallback.
            company = self._first_text(
                card,
                [
                    # Class-based patterns
                    ".company",
                    ".company-name",
                    ".companyName",
                    "[class*='company']",
                    "[class*='Company']",
                    "[class*='employer']",
                    "[class*='Employer']",
                    # Data attribute patterns
                    "[data-testid='company-name']",
                    "[data-testid='companyName']",
                    "[data-testid='company']",
                    "[data-test='company-name']",
                    "[data-company]",
                    # Semantic patterns
                    "span[class*='company']",
                    "div[class*='company']",
                    "p[class*='company']",
                ],
            )
            company = company or "Unknown Company"

            location = self._first_text(
                card,
                [
                    # Class-based patterns (including hashed class from original)
                    "span[class*='location']",
                    "div[class*='location']",
                    "span[class*='Location']",
                    "div[class*='Location']",
                    "span[class*='fxYdFy']",
                    ".location",
                    ".job-location",
                    ".jobLocation",
                    # Data attribute patterns
                    "[data-testid='job-location']",
                    "[data-testid='jobLocation']",
                    "[data-testid='location']",
                    "[data-test='location']",
                    "[data-location]",
                    # Icon-adjacent text patterns
                    "[class*='geo']",
                    "[class*='place']",
                    "[class*='remote']",
                    "[class*='Remote']",
                ],
            )
            location = location or "Remote"

            link_elem = self._first_element(
                card,
                [
                    # Original ID-based selector
                    "a[id^='job-card-title-']",
                    # Data attribute patterns
                    "a[data-testid='job-link']",
                    "a[data-testid='jobLink']",
                    "a[data-test='job-link']",
                    # Class-based patterns
                    "a.job-link",
                    "a.jobLink",
                    "a[class*='job-link']",
                    "a[class*='jobLink']",
                    "a[class*='title']",
                    # URL pattern matching
                    "a[href*='/job/']",
                    "a[href*='/jobs/']",
                    "a[href*='/remote-']",
                    # Generic link fallback
                    "a",
                ],
            )
            href = link_elem.get_attribute("href") if link_elem else ""
            if href and not href.startswith("http"):
                href = f"https://www.remotejobs.io{href}"
            if not href:
                return None

            salary_text = self._first_text(
                card,
                [
                    # Original tag-based selector
                    "li[class*='tag-mint']",
                    "span[class*='tag-mint']",
                    # Class-based patterns
                    ".salary",
                    ".job-salary",
                    ".jobSalary",
                    "[class*='salary']",
                    "[class*='Salary']",
                    "[class*='pay']",
                    "[class*='Pay']",
                    "[class*='compensation']",
                    "[class*='Compensation']",
                    # Data attribute patterns
                    "[data-testid='salary']",
                    "[data-testid='jobSalary']",
                    "[data-test='salary']",
                    # Currency symbol patterns (look for $ € £)
                    "span:has-text('$')",
                    "div:has-text('$')",
                ],
            )
            salary, job_type = self._classify_attribute_text(salary_text)

            if not job_type:
                tag_text = self._first_text(
                    card,
                    [
                        # Original tag-based selector
                        "li[class*='tag-candy']",
                        "span[class*='tag-candy']",
                        # Class-based patterns
                        "[class*='job-type']",
                        "[class*='jobType']",
                        "[class*='JobType']",
                        "[class*='employment']",
                        "[class*='Employment']",
                        # Data attribute patterns
                        "[data-testid='job-type']",
                        "[data-testid='jobType']",
                        "[data-test='job-type']",
                        # Badge/tag patterns
                        "[class*='badge']",
                        "[class*='Badge']",
                        "[class*='tag']",
                        "[class*='Tag']",
                        "[class*='chip']",
                        "[class*='Chip']",
                    ],
                )
                _, found_job_type = self._classify_attribute_text(tag_text)
                if found_job_type:
                    job_type = found_job_type

            description = self._first_text(
                card,
                [
                    # Original ID-based selector
                    "p[id^='job-card-desc-']",
                    # Class-based patterns
                    ".description",
                    ".snippet",
                    ".job-snippet",
                    ".jobSnippet",
                    ".job-description",
                    ".jobDescription",
                    "[class*='description']",
                    "[class*='Description']",
                    "[class*='snippet']",
                    "[class*='Snippet']",
                    "[class*='summary']",
                    "[class*='Summary']",
                    "[class*='excerpt']",
                    "[class*='Excerpt']",
                    # Data attribute patterns
                    "[data-testid='job-snippet']",
                    "[data-testid='jobSnippet']",
                    "[data-testid='description']",
                    "[data-test='job-description']",
                    # Semantic elements
                    "p",
                ],
            )

            date_posted = self._first_text(
                card,
                [
                    # Semantic time element
                    "time",
                    "time[datetime]",
                    # Class-based patterns
                    ".date",
                    ".posted",
                    ".posted-date",
                    ".postedDate",
                    "[class*='date']",
                    "[class*='Date']",
                    "[class*='posted']",
                    "[class*='Posted']",
                    "[class*='time']",
                    "[class*='Time']",
                    "[class*='ago']",
                    "[class*='Ago']",
                    # Data attribute patterns
                    "[data-testid='date-posted']",
                    "[data-testid='datePosted']",
                    "[data-testid='posted']",
                    "[data-test='date']",
                ],
            )

            return Job(
                title=title.strip(),
                company=company.strip(),
                location=location.strip(),
                link=href,
                salary=salary.strip() if salary else None,
                job_type=job_type.strip() if job_type else None,
                description=description.strip(),
                date_posted=date_posted.strip() if date_posted else None,
                source="remotejobs",
            )

        except Exception as e:
            logger.warning(f"Extraction error: {e}")
            return None

    def collect_all(self, queries: List[SearchQuery]) -> List[Job]:
        """Collect jobs for all search queries"""
        all_jobs = []
        global_seen_links: set[str] = set()

        print("\n" + "="*60)
        print("🤖 STARTING JOB COLLECTION")
        print("="*60)

        try:
            self.start_browser()

            for query in queries:
                try:
                    jobs = self.collect_jobs(query, global_seen_links=global_seen_links)
                    all_jobs.extend(jobs)
                    self._random_delay()
                except CaptchaAbort:
                    logger.warning("Aborting run after captcha per user request")
                    print("\n⚠️  Run aborted by user after captcha.")
                    break
                except KeyboardInterrupt:
                    logger.warning("Interrupted during collection; returning partial results")
                    print("\n⚠️  Interrupted - returning partial results")
                    break

        finally:
            self.stop_browser()

        # Remove duplicates based on link
        seen_links = set()
        unique_jobs = []
        for job in all_jobs:
            if str(job.link) not in seen_links:
                seen_links.add(str(job.link))
                unique_jobs.append(job)

        print(f"\n📊 Total: {len(unique_jobs)} unique jobs collected")
        if self.first_captcha_fetch_count is not None:
            print(f"⚠️  Hit captcha after {self.first_captcha_fetch_count} detail fetches")
        print("="*60 + "\n")

        logger.info(f"Collection complete: {len(unique_jobs)} unique jobs")
        return unique_jobs
