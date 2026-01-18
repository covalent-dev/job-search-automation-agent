"""
Job Collector - Playwright-based job listing collector
Handles browser automation and data extraction
"""

import logging
import os
import random
import time
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

    def _random_delay(self) -> None:
        """Add human-like delay between actions"""
        min_delay = self.config.get_min_delay()
        max_delay = self.config.get_max_delay()
        delay = random.uniform(min_delay, max_delay)
        time.sleep(delay)

    def _build_search_url(self, query: SearchQuery) -> str:
        """Build search URL for job board"""
        # Indeed URL structure
        keyword = query.keyword.replace(" ", "+")
        location = query.location.replace(" ", "+")
        return f"https://www.indeed.com/jobs?q={keyword}&l={location}"

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
        url = self._build_search_url(query)

        logger.info(f"Searching: {query}")
        print(f"\n🔍 Searching: {query}")

        try:
            # Navigate to search results
            if not self._safe_goto(url):
                logger.warning("Failed to load search page after retries")
                print("   ✗ Failed to load search page")
                return jobs
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
            matched_selector = None
            for selector in selectors:
                try:
                    self.page.wait_for_selector(selector, timeout=5000)
                    job_cards = self.page.query_selector_all(selector)
                    if job_cards:
                        logger.info(f"Found jobs using selector: {selector}")
                        matched_selector = selector
                        break
                except:
                    continue

            if not job_cards:
                # Debug: save screenshot and HTML
                self.page.screenshot(path="output/debug_screenshot.png")
                logger.warning("No job cards found with any selector")
                print(f"   ⚠️  No job cards found - saved debug screenshot")
                return jobs

            try:
                self.page.wait_for_selector(".job-snippet", timeout=3000)
            except Exception:
                pass

            logger.info(f"Found {len(job_cards)} job cards")
            print(f"   Found {len(job_cards)} listings")

            for i, card in enumerate(job_cards[:query.max_results]):
                try:
                    job = self._extract_job_from_card(card)
                    if job:
                        jobs.append(job)
                        logger.debug(f"Extracted: {job.title} at {job.company}")
                except Exception as e:
                    logger.warning(f"Failed to extract job {i}: {e}")
                    continue

                # Small delay between extractions
                if i % 5 == 0:
                    self._random_delay()

            print(f"   ✓ Collected {len(jobs)} jobs")

        except Exception as e:
            logger.error(f"Error collecting jobs: {e}")
            print(f"   ✗ Error: {e}")

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

            # Salary (optional)
            salary_elem = card.query_selector("[data-testid='attribute_snippet_testid']")
            salary = salary_elem.inner_text() if salary_elem else None

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
