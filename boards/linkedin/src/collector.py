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
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote_plus
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
from models import Job, SearchQuery
from captcha_solver import is_solver_configured, maybe_solve_and_inject

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None

logger = logging.getLogger(__name__)

SESSION_FILE = Path("config/session.json")
REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
REPO_NAME = REPO_ROOT.name
PROFILE_ROOT = Path.home() / ".job-search-automation"
# Match the profile naming used by setup_session.py
USER_DATA_DIR = PROFILE_ROOT / f"job-search-automation-{REPO_NAME}-profile"

if load_dotenv is not None:
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=False)


class CaptchaAbort(Exception):
    """Raised when user opts to abort after captcha."""


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
        self.skip_detail_fetches = False
        self.skip_detail_fetches_logged = False
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
        self.jobs_checkpoint: List[Job] = []
        self.checkpoint_path = Path("output/progress_checkpoint.json")
        self.captcha_log_path = Path("output/captcha_log.json")
        self.captcha_auto_solve_attempted_urls: set[str] = set()

    def _random_delay(self) -> None:
        """Add human-like delay between actions"""
        min_delay = self.config.get_min_delay()
        max_delay = self.config.get_max_delay()
        delay = random.uniform(min_delay, max_delay)
        time.sleep(delay)

    def _looks_like_salary(self, text: str) -> bool:
        if not text:
            return False
        lower = text.lower()
        has_currency = any(symbol in text for symbol in ("$", "€", "£"))
        has_period = any(token in lower for token in ("/yr", "/hr", "/year", "/hour", "per year", "per hour"))
        has_digits = any(ch.isdigit() for ch in text)
        return has_digits and (has_currency or has_period)

    def _scroll_results(self) -> None:
        """Scroll page to encourage lazy-loaded results."""
        try:
            for _ in range(3):
                self.page.mouse.wheel(0, 1200)
                time.sleep(0.5)
        except Exception:
            logger.debug("Scroll failed", exc_info=True)

    def _dismiss_linkedin_overlays(self) -> None:
        """Attempt to close LinkedIn modals that block results."""
        selectors = [
            "button[aria-label='Dismiss']",
            "button[aria-label='Close']",
            ".artdeco-modal__dismiss",
            ".modal__dismiss",
        ]
        for selector in selectors:
            try:
                element = self.page.query_selector(selector)
                if element:
                    element.click()
            except Exception:
                continue

    def _try_auto_solve_captcha(self, page: Page, url: str, *, context: str) -> bool:
        if not page or not url:
            return False
        if url in self.captcha_auto_solve_attempted_urls:
            return False
        if not is_solver_configured(self.config):
            return False

        self.captcha_auto_solve_attempted_urls.add(url)
        print("\n🤖 Attempting automatic captcha solve (if supported)...")
        solved = maybe_solve_and_inject(page, self.config, context=context)
        if not solved:
            return False

        try:
            page.wait_for_timeout(1500)
        except Exception:
            pass

        try:
            submit_button = page.query_selector("form button[type='submit'], button[type='submit']")
            if submit_button:
                try:
                    if submit_button.is_visible():
                        submit_button.click(timeout=1000)
                except Exception:
                    pass
        except Exception:
            pass

        return True

    def _handle_search_captcha(self, page: Page, url: str) -> str:
        self._notify_captcha()
        print("\n⚠️  CAPTCHA or auth wall detected on search page.")
        if self._try_auto_solve_captcha(page, url, context="search"):
            print("✅ Auto-solve attempted; retrying.")
            return "retry"
        print("Choose how to proceed:")
        print("  1) Solve manually (pause and retry)")
        print("  2) Abort run")
        while True:
            choice = input("Enter 1 or 2: ").strip()
            if choice == "1":
                print("\nSolve the challenge in the browser, then press ENTER to retry.")
                input()
                return "retry"
            if choice == "2":
                self.abort_requested = True
                return "abort"
            print("Invalid choice. Please enter 1 or 2.")

    def _build_search_url(self, query: SearchQuery, start: int = 0) -> str:
        """Build search URL for job board"""
        keyword = quote_plus(query.keyword)
        location = quote_plus(query.location)
        base_url = f"https://www.linkedin.com/jobs/search/?keywords={keyword}&location={location}"
        if "remote" in query.location.lower():
            base_url = f"{base_url}&f_WT=2"
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

    def _normalize_line_text(self, text: str) -> str:
        parts = [part.strip() for part in text.splitlines() if part.strip()]
        if not parts:
            return ""
        if len(parts) > 1 and all(part == parts[0] for part in parts):
            return parts[0]
        return " ".join(parts)

    def _clean_title(self, title: str) -> str:
        if not title:
            return title
        cleaned = title.replace(" with verification", "")
        cleaned = cleaned.replace(" With Verification", "")
        # Strip LinkedIn "| $XX/hr - $YY/hr - Remote" suffixes
        pipe_match = re.search(r'\s*\|\s*\$[\d,./\-\s]+(?:hr|yr|hour|year)?(?:\s*-\s*(?:Remote|Hybrid|On-site))?.*$', cleaned, re.IGNORECASE)
        if pipe_match:
            cleaned = cleaned[:pipe_match.start()].strip()
        # Simple exact duplicate detection (e.g., "Title Title" -> "Title")
        tokens = cleaned.split()
        if len(tokens) >= 2 and len(tokens) % 2 == 0:
            half = len(tokens) // 2
            if tokens[:half] == tokens[half:]:
                cleaned = " ".join(tokens[:half])
        # More flexible duplicate detection
        tokens = cleaned.split()
        for n in range(len(tokens) // 2, 4, -1):
            segment = " ".join(tokens[:n])
            rest = " ".join(tokens[n:]).strip()
            if rest.startswith(segment):
                return segment.strip()
        return cleaned.strip()

    def _looks_like_date_posted(self, text: str) -> bool:
        if not text:
            return False
        lowered = text.lower().strip()
        ignore_markers = {
            "promoted",
            "viewed",
            "applied",
            "actively recruiting",
        }
        if lowered in ignore_markers:
            return False
        time_markers = [
            "ago",
            "just now",
            "today",
            "yesterday",
            "hour",
            "hours",
            "day",
            "days",
            "week",
            "weeks",
            "month",
            "months",
            "minute",
            "minutes",
        ]
        return any(marker in lowered for marker in time_markers)

    def _extract_from_detail_pane(self) -> dict:
        """Extract salary, job_type, description, and date_posted from LinkedIn's detail pane.

        This extracts from the right-side pane that appears when clicking a job card,
        avoiding the need for separate page navigation.

        Extraction priority:
        1. JSON-LD structured data (most reliable)
        2. Preference chips (salary, job_type)
        3. Description text regex fallback (salary only)
        """
        result = {
            "salary": None,
            "job_type": None,
            "description": None,
            "date_posted": None,
        }

        try:
            # 1. Try JSON-LD extraction first (most reliable)
            json_salary, json_job_type = self._extract_salary_from_json_ld(self.page)
            if json_salary:
                result["salary"] = json_salary
            if json_job_type:
                result["job_type"] = json_job_type

            # 2. Extract salary and job_type from preference chips
            # Extended selectors for better coverage
            chip_selectors = [
                ".job-details-fit-level-preferences li",
                ".job-details-fit-level-preferences button",
                ".job-details-fit-level-preferences span.tvm__text",
                ".job-details-fit-level-preferences span",
                ".job-details-preferences-and-skills li",
                ".job-details-preferences-and-skills button",
                ".job-details-preferences-and-skills span",
                ".jobs-unified-top-card__job-insight li",
                ".jobs-unified-top-card__job-insight span",
                ".artdeco-entity-lockup__metadata div",
                ".job-details-jobs-unified-top-card__job-insight",
                ".job-details-jobs-unified-top-card__job-insight span",
            ]
            chips_text = []
            seen_texts = set()
            for selector in chip_selectors:
                for elem in self.page.query_selector_all(selector):
                    text = self._extract_text(elem)
                    if text and len(text) < 150 and text not in seen_texts:
                        seen_texts.add(text)
                        chips_text.append(text)

            for text in chips_text:
                # Check for salary (strip benefit suffix first)
                if not result["salary"] and self._looks_like_salary(text):
                    cleaned = self._strip_benefit_suffix(text)
                    normalized = self._normalize_salary_text(cleaned)
                    if normalized:
                        result["salary"] = normalized
                    else:
                        result["salary"] = cleaned
                # Check for job type
                if not result["job_type"]:
                    _, job_type = self._classify_attribute_text(text)
                    if job_type:
                        result["job_type"] = job_type

            # 3. Extract description from detail pane
            desc_selectors = [
                "div.jobs-box__html-content#job-details",
                "div#job-details",
                "div.jobs-description__content",
                "div.jobs-description-content__text",
                "section.jobs-description",
                "article.jobs-description__container",
                ".show-more-less-html__markup",
            ]
            for selector in desc_selectors:
                elem = self.page.query_selector(selector)
                if elem:
                    text = self._extract_text(elem)
                    if text and len(text) > 50:  # Descriptions should be substantial
                        result["description"] = text
                        break

            # 4. Regex fallback: try to extract salary from description if not found
            if not result["salary"] and result["description"]:
                desc_salary = self._extract_salary_from_description(result["description"])
                if desc_salary:
                    result["salary"] = desc_salary

            # 5. Extract posted date from top card
            date_selectors = [
                ".job-details-jobs-unified-top-card__tertiary-description-container",
                ".job-details-jobs-unified-top-card__primary-description-container",
                ".jobs-unified-top-card__subtitle-secondary-grouping",
                "span.jobs-unified-top-card__posted-date",
                ".artdeco-entity-lockup__caption",
                "time",
            ]
            for selector in date_selectors:
                elem = self.page.query_selector(selector)
                if elem:
                    text = self._extract_text(elem)
                    # Look for time-related text within the element
                    if text:
                        # Split by common separators and find date-like portion
                        for part in re.split(r'[·•|]', text):
                            part = part.strip()
                            if self._looks_like_date_posted(part):
                                result["date_posted"] = part
                                break
                        if result["date_posted"]:
                            break

        except Exception as exc:
            logger.debug("Detail pane extraction failed: %s", exc)

        return result

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

    def _handle_captcha_prompt(self, page: Page, url: str) -> str:
        self._log_captcha(url)
        self._notify_captcha()
        print("\n⚠️  CAPTCHA detected during detail fetch.")
        if self._try_auto_solve_captcha(page, url, context="detail"):
            print("✅ Auto-solve attempted; retrying.")
            return "retry"
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

    def _strip_benefit_suffix(self, salary_text: str) -> str:
        """Strip benefit suffixes like '· Medical, +1 benefit' from salary text."""
        if not salary_text:
            return salary_text
        # Pattern: salary · benefit text
        # Examples: "$25/hr · Medical, +1 benefit", "$150K/yr - $190K/yr · Vision, +3 benefits"
        match = re.match(r'^([^·]+)', salary_text)
        if match:
            return match.group(1).strip()
        return salary_text.strip()

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
            return None
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

    def _extract_salary_from_description(self, description: str) -> Optional[str]:
        """Extract salary from job description text using regex patterns."""
        if not description:
            return None

        # Patterns to match salary mentions in description text
        patterns = [
            # Range patterns: $XX - $YY per hour/year, $XXk - $XXXk
            r'\$\s?(\d[\d,]*(?:\.\d+)?)\s*[kK]?\s*[-–—to]+\s*\$?\s?(\d[\d,]*(?:\.\d+)?)\s*[kK]?\s*(?:per\s+)?(hour|hr|year|yr|annually)\b',
            # Single value: $XX per hour/year, $XXk/yr
            r'\$\s?(\d[\d,]*(?:\.\d+)?)\s*[kK]?\s*(?:per\s+|/)?(hour|hr|year|yr|annually)\b',
            # Range with k suffix: $120k - $150k
            r'\$\s?(\d+)\s*[kK]\s*[-–—to]+\s*\$?\s?(\d+)\s*[kK]\b',
            # Hourly range without unit: $25 - $35/hr
            r'\$\s?(\d+(?:\.\d+)?)\s*[-–—to]+\s*\$?\s?(\d+(?:\.\d+)?)\s*/\s*(hr|hour)\b',
            # Salary: $XXX,XXX patterns
            r'salary[:\s]+\$?\s?(\d[\d,]+)\s*(?:[-–—to]+\s*\$?\s?(\d[\d,]+))?\s*(?:per\s+)?(year|annually)?',
            # Compensation: $XX/hr or $XXk
            r'compensation[:\s]+\$?\s?(\d[\d,]*(?:\.\d+)?)\s*[kK]?\s*(?:per\s+|/)?(hour|hr|year|yr)?',
        ]

        for pattern in patterns:
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                groups = match.groups()
                # Try to normalize the found salary
                extracted = match.group(0)
                normalized = self._normalize_salary_text(extracted)
                if normalized:
                    return normalized
                # If normalization failed, try to build from captured groups
                if len(groups) >= 2 and groups[0]:
                    try:
                        min_val = groups[0].replace(',', '')
                        max_val = groups[1].replace(',', '') if groups[1] else None
                        unit = groups[2] if len(groups) > 2 else None

                        # Handle k suffix
                        if 'k' in extracted.lower():
                            min_val = str(float(min_val) * 1000)
                            if max_val:
                                max_val = str(float(max_val) * 1000)

                        min_float = float(min_val)
                        max_float = float(max_val) if max_val else None

                        # Determine unit
                        unit_norm = None
                        if unit:
                            if unit.lower() in ('hr', 'hour'):
                                unit_norm = 'hour'
                            elif unit.lower() in ('yr', 'year', 'annually'):
                                unit_norm = 'year'
                        elif min_float > 500:  # Likely annual if > 500
                            unit_norm = 'year'

                        return self._format_salary('$', min_float, max_float, unit_norm)
                    except (ValueError, TypeError):
                        pass

        return None

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
                "checkpoint/challenge",
                "/authwall",
            ]
            for marker in url_markers:
                if marker in url:
                    return {"reason": f"url:{marker}", "title": title, "url": url}

            job_card_selectors = [
                "div.job-card-container",
                "li.jobs-search-results__list-item",
                "div.jobs-search-results__list-item",
            ]
            for selector in job_card_selectors:
                if page.query_selector(selector):
                    return None

            def _visible(selector: str) -> bool:
                handle = page.query_selector(selector)
                if not handle:
                    return False
                try:
                    return handle.is_visible()
                except Exception:
                    return True

            selector_markers = {
                "#cf-challenge-running": "selector:#cf-challenge-running",
                "form#challenge-form": "selector:form#challenge-form",
                "iframe[src*='challenges.cloudflare.com']": "selector:cloudflare-iframe",
                "iframe[src*='hcaptcha.com']": "selector:hcaptcha-iframe",
                "iframe[src*='recaptcha']": "selector:recaptcha-iframe",
                ".cf-turnstile": "selector:cf-turnstile",
                "[data-sitekey]": "selector:data-sitekey",
                "div#captcha-internal": "selector:captcha-internal",
                "div#recaptcha-element": "selector:recaptcha-element",
                "div.authwall-join-form": "selector:authwall-join-form",
                "div.authwall-join-form__title": "selector:authwall-join-form__title",
            }
            for selector, reason in selector_markers.items():
                if selector in (
                    "iframe[src*='hcaptcha.com']",
                    "iframe[src*='recaptcha']",
                    ".cf-turnstile",
                    "[data-sitekey]",
                ):
                    if _visible(selector):
                        return {"reason": reason, "title": title, "url": url}
                    continue
                if page.query_selector(selector):
                    return {"reason": reason, "title": title, "url": url}

            body = (page.inner_text("body") or "").lower()
            authwall_markers = [
                "sign in to linkedin",
                "join linkedin",
                "security verification",
                "additional verification required",
                "verify you are human",
                "authwall",
            ]
            for marker in authwall_markers:
                if marker in body:
                    return {"reason": f"body:{marker}", "title": title, "url": url}
            return None
        except Exception:
            return None

    def _fetch_detail_salary(self, url: str) -> tuple[Optional[str], Optional[str]]:
        if not self.context or not url:
            return None, None
        if self.skip_detail_fetches:
            if not self.skip_detail_fetches_logged:
                logger.info("Skipping optional detail salary fetches (skip mode active)")
                self.skip_detail_fetches_logged = True
            return None, None

        if url in self.detail_salary_cache:
            return self.detail_salary_cache[url]

        timeout_ms = self.config.get_detail_salary_timeout() * 1000
        retries = self.config.get_detail_salary_retries()
        delay_min = self.config.get_detail_salary_delay_min()
        delay_max = self.config.get_detail_salary_delay_max()
        salary_selectors = [
            # LinkedIn selectors
            ".job-details-fit-level-preferences li",
            ".job-details-fit-level-preferences button",
            ".job-details-fit-level-preferences span",
            ".job-details-preferences-and-skills li",
            ".jobs-unified-top-card__job-insight",
            # Indeed selectors (fallback for other boards)
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
            # LinkedIn selectors
            ".job-details-jobs-unified-top-card__container--two-pane",
            "div.jobs-description__content",
            "div#job-details",
            # Indeed selectors (fallback)
            "section[aria-label='Job details']",
            "[data-testid='jobDetailsSection']",
            "#jobDetailsSection",
        ]

        salary = None
        job_type = None

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
                try:
                    detail_page.wait_for_url("**/viewjob?jk=**", timeout=3000)
                except Exception:
                    pass
                try:
                    detail_page.wait_for_selector(
                        "section[aria-label='Job details'], [data-testid='jobDetailsSection'], #jobDetailsSection",
                        timeout=3000,
                    )
                except Exception:
                    pass
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
                        "Detail salary fetch blocked by captcha (reason=%s, title=%s, url=%s)",
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
                    action = self._handle_captcha_prompt(detail_page, url)
                    if action == "abort":
                        raise CaptchaAbort("User requested abort after captcha")
                    if action == "skip":
                        return None, None
                    if action == "retry":
                        self.detail_salary_page = None
                        attempt = max(attempt - 1, 0)
                        continue
                else:
                    self.captcha_consecutive = 0

                if not salary or not job_type:
                    json_salary, json_job_type = self._extract_salary_from_json_ld(detail_page)
                    if json_salary and not salary:
                        salary = json_salary
                    if json_job_type and not job_type:
                        job_type = json_job_type

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
                    if found_salary and not salary:
                        salary = found_salary
                    if found_job_type and not job_type:
                        job_type = found_job_type
                    if salary and job_type:
                        break

                if not salary and not self.detail_debug_saved:
                    try:
                        Path("output").mkdir(parents=True, exist_ok=True)
                        detail_page.screenshot(path="output/detail_debug.png")
                        Path("output/detail_debug.html").write_text(
                            detail_page.content(), encoding="utf-8"
                        )
                        self.detail_debug_saved = True
                    except Exception:
                        pass

                if salary or job_type:
                    break

            except Exception as exc:
                if isinstance(exc, CaptchaAbort):
                    raise
                if "Target page, context or browser has been closed" in str(exc):
                    self.detail_salary_page = None
                logger.warning("Detail salary fetch failed (attempt %s/%s): %s", attempt, retries, exc)
                self._random_delay()

        self.detail_salary_cache[url] = (salary, job_type)
        return salary, job_type

    def _fetch_detail_description(self, url: str) -> Optional[str]:
        if not self.context or not url:
            return None
        if self.skip_detail_fetches:
            if not self.skip_detail_fetches_logged:
                logger.info("Skipping optional detail description fetches (skip mode active)")
                self.skip_detail_fetches_logged = True
            return None
        if url in self.detail_description_cache:
            return self.detail_description_cache[url]

        timeout_ms = self.config.get_detail_description_timeout() * 1000
        retries = self.config.get_detail_description_retries()
        delay_min = self.config.get_detail_description_delay_min()
        delay_max = self.config.get_detail_description_delay_max()

        description = None
        attempt = 0
        selectors = [
            # LinkedIn selectors (prioritized)
            "div.jobs-box__html-content#job-details",
            "div#job-details",
            "div.jobs-description__content",
            "div.jobs-box__html-content",
            "article.jobs-description__container",
            ".show-more-less-html__markup",
            "div.show-more-less-html__markup",
            "section.show-more-less-html",
            "div.description__text",
            "[data-test-id='job-description']",
        ]

        while attempt < retries:
            try:
                attempt += 1
                if self.detail_description_page is not None and self.detail_description_page.is_closed():
                    self.detail_description_page = None
                if self.detail_description_page is None:
                    self.detail_description_page = self.context.new_page()
                    self.detail_description_page.set_default_timeout(timeout_ms)
                    self.detail_description_page.set_default_navigation_timeout(timeout_ms)
                detail_page = self.detail_description_page
                if delay_max > 0:
                    time.sleep(random.uniform(delay_min, delay_max))
                detail_page.goto(url, wait_until="domcontentloaded")
                try:
                    detail_page.wait_for_selector(", ".join(selectors), timeout=3000)
                except Exception:
                    pass
                captcha_detection = self._is_captcha_page(detail_page)
                if captcha_detection:
                    self.captcha_consecutive += 1
                    logger.warning(
                        "Detail description fetch blocked by captcha (reason=%s, title=%s, url=%s)",
                        captcha_detection["reason"],
                        captcha_detection["title"],
                        captcha_detection["url"],
                    )
                    self._captcha_backoff()
                    action = self._handle_captcha_prompt(detail_page, url)
                    if action == "abort":
                        raise CaptchaAbort("User requested abort after captcha")
                    if action == "skip":
                        return None
                    if action == "retry":
                        self.detail_description_page = None
                        attempt = max(attempt - 1, 0)
                        continue
                else:
                    self.captcha_consecutive = 0

                for selector in selectors:
                    elem = detail_page.query_selector(selector)
                    text = self._extract_text(elem)
                    if text and (not description or len(text) > len(description)):
                        description = text

                if not description and not self.detail_description_debug_saved:
                    try:
                        Path("output").mkdir(parents=True, exist_ok=True)
                        detail_page.screenshot(path="output/detail_description_debug.png")
                        Path("output/detail_description_debug.html").write_text(
                            detail_page.content(), encoding="utf-8"
                        )
                        self.detail_description_debug_saved = True
                    except Exception:
                        pass

                if description:
                    break

            except Exception as exc:
                if isinstance(exc, CaptchaAbort):
                    raise
                if "Target page, context or browser has been closed" in str(exc):
                    self.detail_description_page = None
                logger.warning(
                    "Detail description fetch failed (attempt %s/%s): %s",
                    attempt,
                    retries,
                    exc,
                )
                self._random_delay()

        self.detail_description_cache[url] = description
        return description


    def _safe_goto(self, url: str) -> bool:
        """Navigate with retry for flaky pages."""
        for attempt in range(1, self.max_retries + 1):
            try:
                self.page.goto(url, wait_until="domcontentloaded")
                return True
            except Exception as exc:
                logger.warning("Navigation failed (attempt %s/%s): %s", attempt, self.max_retries, exc)
                self._random_delay()
        return False

    def _has_next_page(self) -> bool:
        """Check if a next page control exists and is enabled."""
        selectors = [
            "a[aria-label='Next Page']",
            "a[aria-label='Next']",
            "a[aria-label='Next page']",
            "button[aria-label='Next']",
            "button[aria-label='Next Page']",
            "button.artdeco-pagination__button--next",
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

        if executable_path and not Path(executable_path).exists():
            logger.warning("Browser executable not found: %s", executable_path)
            executable_path = None

        # Build proxy config if enabled
        proxy_config = self.config.get_proxy_config()
        if proxy_config:
            logger.info("Proxy enabled: %s", proxy_config.get("server", ""))
        else:
            logger.info("Proxy disabled")

        # Check if persistent profile exists (preferred method)
        if self.user_data_dir.exists():
            logger.info(f"Using persistent profile: {self.user_data_dir}")
            launch_kwargs = {
                "user_data_dir": str(self.user_data_dir),
                "headless": self.config.is_headless(),
                "viewport": {"width": 1280, "height": 800},
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
                "channel": channel,
                "executable_path": executable_path,
                "timeout": launch_timeout,
            }
            if proxy_config:
                launch_kwargs["proxy"] = proxy_config
            self.context = self.playwright.chromium.launch_persistent_context(**launch_kwargs)
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        else:
            # Fallback to session file or new context
            logger.info("No persistent profile found, using regular context")
            launch_kwargs = {
                "headless": self.config.is_headless(),
                "channel": channel,
                "executable_path": executable_path,
                "timeout": launch_timeout,
            }
            if proxy_config:
                launch_kwargs["proxy"] = proxy_config
            self.browser = self.playwright.chromium.launch(**launch_kwargs)

            context_kwargs = {"viewport": {"width": 1280, "height": 800}}
            if proxy_config:
                context_kwargs["proxy"] = proxy_config
            if self.session_file.exists():
                logger.info(f"Loading session from {self.session_file}")
                context_kwargs["storage_state"] = str(self.session_file)
            else:
                logger.warning("No session found - run setup_session.py first!")
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

    def collect_jobs(self, query: SearchQuery) -> List[Job]:
        """Collect jobs for a single search query"""
        jobs = []
        seen_links = set()
        max_pages = self.config.get_max_pages()
        unlimited_pages = max_pages <= 0
        results_per_page = 25
        max_detail_fetches = self.config.get_detail_salary_max_per_query()
        unlimited_detail_fetches = max_detail_fetches <= 0
        detail_fetches = 0
        max_detail_description_fetches = self.config.get_detail_description_max_per_query()
        unlimited_detail_description_fetches = max_detail_description_fetches <= 0
        detail_description_fetches = 0

        last_first_link = None
        self.current_query = str(query)
        page_index = 0
        while True:
            if not unlimited_pages and page_index >= max_pages:
                break
            start = page_index * results_per_page
            url = self._build_search_url(query, start=start)
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
                captcha_detection = self._is_captcha_page(self.page)
                if captcha_detection:
                    logger.warning(
                        "Search page blocked (reason=%s, title=%s, url=%s)",
                        captcha_detection["reason"],
                        captcha_detection["title"],
                        captcha_detection["url"],
                    )
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    Path("output").mkdir(parents=True, exist_ok=True)
                    self.page.screenshot(path=f"output/search_captcha_{timestamp}.png")
                    Path(f"output/search_captcha_{timestamp}.html").write_text(
                        self.page.content(), encoding="utf-8"
                    )
                    action = self._handle_search_captcha(self.page, url)
                    if action == "abort":
                        raise CaptchaAbort("User requested abort after captcha")
                    if not self._safe_goto(url):
                        logger.warning("Failed to reload after captcha")
                        break
                    self._random_delay()
                self._dismiss_linkedin_overlays()
                self._scroll_results()

                # Try multiple selectors (LinkedIn variants)
                selectors = [
                    "ul.jobs-search__results-list li",
                    "li.jobs-search-results__list-item",
                    "div.job-card-container",
                    "div.base-card",
                    "div.job-search-card"
                ]

                job_cards = []
                for selector in selectors:
                    try:
                        self.page.wait_for_selector(selector, timeout=5000)
                        job_cards = self.page.query_selector_all(selector)
                        if job_cards:
                            logger.info("Found jobs using selector: %s", selector)
                            break
                    except Exception:
                        continue

                if not job_cards:
                    # Debug: save screenshot and HTML
                    Path("output").mkdir(parents=True, exist_ok=True)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    self.page.screenshot(path=f"output/debug_screenshot_{timestamp}.png")
                    Path(f"output/debug_page_{timestamp}.html").write_text(
                        self.page.content(), encoding="utf-8"
                    )
                    logger.warning("No job cards found with any selector")
                    print("   ⚠️  No job cards found - saved debug screenshot + HTML")
                    break

                try:
                    self.page.wait_for_selector("h3", timeout=3000)
                except Exception:
                    pass

                logger.info("Found %s job cards", len(job_cards))
                print(f"   Found {len(job_cards)} listings")
                remaining_cap = query.max_results - len(jobs) if query.max_results > 0 else len(job_cards)
                progress_total = min(len(job_cards), remaining_cap) if remaining_cap > 0 else len(job_cards)

                added_this_page = 0
                first_link = None
                for i, card in enumerate(job_cards):
                    if len(jobs) >= query.max_results:
                        break
                    if progress_total > 0:
                        progress_current = min(i + 1, progress_total)
                        print(f"\r   Progress: {progress_current}/{progress_total}", end="", flush=True)
                    try:
                        job = self._extract_job_from_card(card)
                        if job and str(job.link) not in seen_links:
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

                            seen_links.add(str(job.link))
                            jobs.append(job)
                            self.total_jobs_collected += 1
                            if job.salary:
                                self.total_jobs_with_salary += 1
                            self.jobs_checkpoint.append(job)
                            if self.total_jobs_collected % 25 == 0:
                                self._write_checkpoint(self.jobs_checkpoint)
                            added_this_page += 1
                            logger.debug("Extracted: %s at %s", job.title, job.company)
                        if first_link is None and job:
                            first_link = str(job.link)
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

            if len(jobs) >= query.max_results:
                break

            page_index += 1

        return jobs

    def _extract_job_from_card(self, card, click_for_details: bool = True) -> Optional[Job]:
        """Extract job data from a single job card element.

        Args:
            card: The job card element
            click_for_details: If True, click the card to load detail pane and extract
                              salary, job_type, description from there (reduces separate navigations)
        """
        try:
            # Title
            title_elem = (
                card.query_selector("a.job-card-container__link")
                or card.query_selector("a.job-card-list__title--link")
                or card.query_selector("h3")
            )
            title = self._extract_text(title_elem) if title_elem else "Unknown Title"
            title = self._normalize_line_text(title)
            title = self._clean_title(title)

            # Company
            company_elem = (
                card.query_selector(".artdeco-entity-lockup__subtitle span")
                or card.query_selector(".job-card-container__company-name")
                or card.query_selector("a.job-card-container__company-name")
                or card.query_selector("h4")
            )
            company = self._extract_text(company_elem) if company_elem else "Unknown Company"

            # Location and Salary from card metadata
            location = None
            salary = None
            # Extended selectors to catch salary from various card layouts
            metadata_selectors = [
                "ul.job-card-container__metadata-wrapper li span",
                ".artdeco-entity-lockup__metadata div",
                ".job-card-container__metadata-item",
                ".job-card-list__insight span",
            ]
            for selector in metadata_selectors:
                for item in card.query_selector_all(selector):
                    text = self._extract_text(item)
                    if not text:
                        continue
                    if self._looks_like_salary(text) and not salary:
                        # Strip benefit suffix and normalize
                        cleaned = self._strip_benefit_suffix(text)
                        normalized = self._normalize_salary_text(cleaned)
                        salary = normalized if normalized else cleaned
                        continue
                    if not location and not self._looks_like_salary(text):
                        # Avoid setting location to salary text
                        location = text
            if not location:
                location_elem = card.query_selector("span.job-search-card__location")
                if not location_elem:
                    location_elem = card.query_selector(".artdeco-entity-lockup__caption div")
                location = self._extract_text(location_elem) if location_elem else "Unknown Location"

            # Link
            link_elem = (
                card.query_selector("a.job-card-container__link")
                or card.query_selector("a.job-card-list__title--link")
                or card.query_selector("a.base-card__full-link")
            )
            href = link_elem.get_attribute("href") if link_elem else ""
            if not href:
                return None
            if href.startswith("/"):
                href = f"https://www.linkedin.com{href}"
            href = href.split("?")[0]

            # Salary/job type (rare on LinkedIn list cards)
            job_type = None

            # Description snippet (often not present on list card)
            desc_elem = card.query_selector(".job-search-card__snippet")
            description = self._extract_text(desc_elem) if desc_elem else ""
            description_full = None

            # Date posted from card
            date_posted = None
            date_elem = card.query_selector("time")
            if date_elem:
                date_posted = self._extract_text(date_elem)
            if not date_posted:
                footer_items = card.query_selector_all(".job-card-container__footer-item")
                for item in footer_items:
                    text = self._extract_text(item)
                    if self._looks_like_date_posted(text):
                        date_posted = text
                        break

            # Click card to load detail pane and extract additional fields
            # NOTE: Detail pane extraction always runs - it's the primary strategy.
            # skip_detail_fetches only disables optional separate page navigations.
            if click_for_details:
                try:
                    # Click the card to show detail pane
                    clickable = (
                        card.query_selector("a.job-card-container__link")
                        or card.query_selector("a.job-card-list__title--link")
                        or card
                    )
                    if clickable:
                        clickable.click()
                        # Wait for detail pane to load
                        try:
                            self.page.wait_for_selector(
                                ".job-details-jobs-unified-top-card__container--two-pane, "
                                "div.jobs-description__content, "
                                "div#job-details",
                                timeout=3000
                            )
                        except Exception:
                            pass
                        time.sleep(0.3)  # Brief settle time

                        # Extract from detail pane
                        detail_data = self._extract_from_detail_pane()

                        # Merge detail pane data (prefer detail pane over card data)
                        if detail_data.get("salary") and not salary:
                            salary = detail_data["salary"]
                        if detail_data.get("job_type") and not job_type:
                            job_type = detail_data["job_type"]
                        if detail_data.get("description"):
                            description_full = detail_data["description"]
                        if detail_data.get("date_posted") and not date_posted:
                            date_posted = detail_data["date_posted"]

                except Exception as exc:
                    logger.debug("Detail pane click/extract failed: %s", exc)

            return Job(
                title=title.strip(),
                company=company.strip(),
                location=location.strip(),
                link=href,
                salary=salary.strip() if salary else None,
                job_type=job_type.strip() if job_type else None,
                description=description.strip(),
                description_full=description_full.strip() if description_full else None,
                date_posted=date_posted.strip() if date_posted else None,
                source="linkedin"
            )

        except Exception as e:
            logger.warning(f"Extraction error: {e}")
            return None

    def collect_all(self, queries: List[SearchQuery]) -> List[Job]:
        """Collect jobs for all search queries"""
        all_jobs = []

        print("\n" + "="*60)
        print("🤖 STARTING JOB COLLECTION")
        print("="*60)

        try:
            self.start_browser()

            for query in queries:
                try:
                    jobs = self.collect_jobs(query)
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
