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
from pathlib import Path
from typing import List, Optional
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
from models import Job, SearchQuery

logger = logging.getLogger(__name__)

SESSION_FILE = Path("config/session.json")
USER_DATA_DIR = Path.home() / ".job-search-automation" / "browser-profile"


class JobCollector:
    """Collects job listings using Playwright browser automation"""

    def __init__(self, config):
        self.config = config
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.detail_salary_page: Optional[Page] = None
        self.session_file = SESSION_FILE
        self.user_data_dir = USER_DATA_DIR
        self.max_retries = self.config.get_max_retries()
        self.detail_salary_cache: dict[str, tuple[Optional[str], Optional[str]]] = {}
        self.detail_salary_blocked = False
        self.detail_debug_saved = False

    def _random_delay(self) -> None:
        """Add human-like delay between actions"""
        min_delay = self.config.get_min_delay()
        max_delay = self.config.get_max_delay()
        delay = random.uniform(min_delay, max_delay)
        time.sleep(delay)

    def _build_search_url(self, query: SearchQuery, start: int = 0) -> str:
        """Build search URL for job board"""
        # Indeed URL structure
        keyword = query.keyword.replace(" ", "+")
        location = query.location.replace(" ", "+")
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

    def _is_captcha_page(self, page: Page) -> bool:
        try:
            title = (page.title() or "").lower()
            if "additional verification required" in title or "cloudflare" in title:
                return True
            body = (page.inner_text("body") or "").lower()
            captcha_markers = [
                "additional verification required",
                "verify you are human",
                "cloudflare",
            ]
            return any(marker in body for marker in captcha_markers)
        except Exception:
            return False

    def _fetch_detail_salary(self, url: str) -> tuple[Optional[str], Optional[str]]:
        if not self.context or not url:
            return None, None
        if self.detail_salary_blocked:
            return None, None

        if url in self.detail_salary_cache:
            return self.detail_salary_cache[url]

        timeout_ms = self.config.get_detail_salary_timeout() * 1000
        retries = self.config.get_detail_salary_retries()
        delay_min = self.config.get_detail_salary_delay_min()
        delay_max = self.config.get_detail_salary_delay_max()
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

        salary = None
        job_type = None

        for attempt in range(1, retries + 1):
            try:
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
                if self._is_captcha_page(detail_page):
                    logger.warning("Detail salary fetch blocked by captcha; disabling detail fetches")
                    try:
                        detail_page.screenshot(path="output/detail_captcha.png")
                    except Exception:
                        pass
                    self.detail_salary_blocked = True
                    break

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
                logger.warning("Detail salary fetch failed (attempt %s/%s): %s", attempt, retries, exc)
                self._random_delay()

        self.detail_salary_cache[url] = (salary, job_type)
        return salary, job_type


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

        # Check if persistent profile exists (preferred method)
        if self.user_data_dir.exists():
            logger.info(f"Using persistent profile: {self.user_data_dir}")
            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.user_data_dir),
                headless=self.config.is_headless(),
                viewport={"width": 1280, "height": 800},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
                channel=channel,
                executable_path=executable_path,
                timeout=launch_timeout,
            )
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        else:
            # Fallback to session file or new context
            logger.info("No persistent profile found, using regular context")
            self.browser = self.playwright.chromium.launch(
                headless=self.config.is_headless(),
                channel=channel,
                executable_path=executable_path,
                timeout=launch_timeout,
            )

            if self.session_file.exists():
                logger.info(f"Loading session from {self.session_file}")
                self.context = self.browser.new_context(
                    storage_state=str(self.session_file),
                    viewport={"width": 1280, "height": 800},
                )
            else:
                logger.warning("No session found - run setup_session.py first!")
                self.context = self.browser.new_context(
                    viewport={"width": 1280, "height": 800},
                )

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
        results_per_page = 10
        max_detail_fetches = self.config.get_detail_salary_max_per_query()
        unlimited_detail_fetches = max_detail_fetches <= 0
        detail_fetches = 0

        last_first_link = None
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

                # Try multiple selectors (Indeed changes these frequently)
                selectors = [
                    ".job_seen_beacon",
                    ".jobsearch-ResultsList > li",
                    "[data-testid='jobListing']",
                    ".resultContent",
                    ".tapItem"
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
                    self.page.screenshot(path="output/debug_screenshot.png")
                    logger.warning("No job cards found with any selector")
                    print("   ⚠️  No job cards found - saved debug screenshot")
                    break

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
                                and (unlimited_detail_fetches or detail_fetches < max_detail_fetches)
                            ):
                                if unlimited_detail_fetches:
                                    fetch_label = f"{detail_fetches + 1}/∞"
                                else:
                                    fetch_label = f"{detail_fetches + 1}/{max_detail_fetches}"
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

                            seen_links.add(str(job.link))
                            jobs.append(job)
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

    def _extract_job_from_card(self, card) -> Optional[Job]:
        """Extract job data from a single job card element"""
        try:
            # Title
            title_elem = card.query_selector("h2.jobTitle span")
            title = title_elem.inner_text() if title_elem else "Unknown Title"

            # Company
            company_elem = card.query_selector("[data-testid='company-name']")
            company = company_elem.inner_text() if company_elem else "Unknown Company"

            # Location
            location_elem = card.query_selector("[data-testid='text-location']")
            location = location_elem.inner_text() if location_elem else "Unknown Location"

            # Link
            link_elem = card.query_selector("h2.jobTitle a")
            href = link_elem.get_attribute("href") if link_elem else ""
            if href and not href.startswith("http"):
                href = f"https://www.indeed.com{href}"

            # Salary/job type (optional)
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

            # Description snippet
            desc_elem = card.query_selector(".job-snippet")
            description = desc_elem.inner_text() if desc_elem else ""

            # Date posted
            date_elem = card.query_selector(".date")
            date_posted = date_elem.inner_text() if date_elem else None

            return Job(
                title=title.strip(),
                company=company.strip(),
                location=location.strip(),
                link=href,
                salary=salary.strip() if salary else None,
                job_type=job_type.strip() if job_type else None,
                description=description.strip(),
                date_posted=date_posted.strip() if date_posted else None,
                source="indeed"
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
        print("="*60 + "\n")

        logger.info(f"Collection complete: {len(unique_jobs)} unique jobs")
        return unique_jobs
