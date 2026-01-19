"""
Job Collector - Playwright-based job listing collector
Handles browser automation and data extraction
"""

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
        self.session_file = SESSION_FILE
        self.user_data_dir = USER_DATA_DIR
        self.max_retries = self.config.get_max_retries()
        self.detail_salary_cache: dict[str, tuple[Optional[str], Optional[str]]] = {}

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
            "part-time": "Part-time",
            "contract": "Contract",
            "temporary": "Temporary",
            "internship": "Internship",
            "seasonal": "Seasonal",
            "apprenticeship": "Apprenticeship",
        }
        job_types = []
        for key, label in job_type_map.items():
            if key in lower:
                job_types.append(label)

        job_type = ", ".join(job_types) if job_types else None

        salary = None
        salary_pattern = (
            r"(?:estimated\s+)?"
            r"[$£€]\s?\d[\d,]*(?:\.\d+)?"
            r"(?:\s*-\s*[$£€]?\s?\d[\d,]*(?:\.\d+)?)?"
            r"\s*(?:an?|per)?\s*(?:hour|year|yr|month|week|day)"
        )
        match = re.search(salary_pattern, normalized, re.IGNORECASE)
        if match:
            salary = match.group(0).strip()

        return salary, job_type

    def _fetch_detail_salary(self, url: str) -> tuple[Optional[str], Optional[str]]:
        if not self.context or not url:
            return None, None

        if url in self.detail_salary_cache:
            return self.detail_salary_cache[url]

        timeout_ms = self.config.get_detail_salary_timeout() * 1000
        retries = self.config.get_detail_salary_retries()
        selectors = [
            "[data-testid='jobsearch-JobInfoHeader-salary']",
            "[data-testid='salary-snippet']",
            ".salary-snippet",
            "section[aria-label='Job details']",
        ]

        salary = None
        job_type = None

        for attempt in range(1, retries + 1):
            detail_page = None
            try:
                detail_page = self.context.new_page()
                detail_page.set_default_timeout(timeout_ms)
                detail_page.set_default_navigation_timeout(timeout_ms)
                detail_page.goto(url, wait_until="domcontentloaded")

                for selector in selectors:
                    element = detail_page.query_selector(selector)
                    if not element:
                        continue
                    text = self._extract_text(element)
                    if not text:
                        continue
                    found_salary, found_job_type = self._classify_attribute_text(text)
                    if found_salary and not salary:
                        salary = found_salary
                    if found_job_type and not job_type:
                        job_type = found_job_type
                    if salary and job_type:
                        break

                if not salary or not job_type:
                    body_text = detail_page.inner_text("body")
                    found_salary, found_job_type = self._classify_attribute_text(body_text)
                    if found_salary and not salary:
                        salary = found_salary
                    if found_job_type and not job_type:
                        job_type = found_job_type

                if salary or job_type:
                    break

            except Exception as exc:
                logger.warning("Detail salary fetch failed (attempt %s/%s): %s", attempt, retries, exc)
                self._random_delay()
            finally:
                if detail_page:
                    detail_page.close()

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
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        logger.info("Browser closed")

    def collect_jobs(self, query: SearchQuery) -> List[Job]:
        """Collect jobs for a single search query"""
        jobs = []
        seen_links = set()
        max_pages = self.config.get_max_pages()
        unlimited_pages = max_pages <= 0
        results_per_page = 10
        max_detail_fetches = self.config.get_detail_salary_max_per_query()
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

                added_this_page = 0
                first_link = None
                for i, card in enumerate(job_cards):
                    if len(jobs) >= query.max_results:
                        break
                    try:
                        job = self._extract_job_from_card(card)
                        if job and str(job.link) not in seen_links:
                            if (
                                self.config.is_detail_salary_enabled()
                                and not job.salary
                                and job.link
                                and detail_fetches < max_detail_fetches
                            ):
                                detail_salary, detail_job_type = self._fetch_detail_salary(str(job.link))
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

                print(f"   ✓ Collected {len(jobs)} jobs")

                if added_this_page == 0:
                    logger.info("No new jobs added on page %s; stopping pagination", page_index + 1)
                    break

                if first_link and last_first_link and first_link == last_first_link:
                    logger.info("First result repeated on page %s; stopping pagination", page_index + 1)
                    break
                if first_link:
                    last_first_link = first_link

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
                jobs = self.collect_jobs(query)
                all_jobs.extend(jobs)
                self._random_delay()

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
