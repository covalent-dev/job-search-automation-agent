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
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
try:
    from models import Job, SearchQuery
except ModuleNotFoundError:  # pragma: no cover
    from shared.models import Job, SearchQuery
try:
    from captcha_solver import TwoCaptchaSolver, CaptchaSolveError
except ModuleNotFoundError:  # pragma: no cover
    from shared.captcha_solver import TwoCaptchaSolver, CaptchaSolveError
logger = logging.getLogger(__name__)

SESSION_FILE = Path("config/session.json")
REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_NAME = REPO_ROOT.name
PROFILE_ROOT = Path.home() / ".job-search-automation"
# Match the profile naming used by setup_session.py
USER_DATA_DIR = PROFILE_ROOT / f"job-search-automation-{REPO_NAME}-profile"


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
        self._captcha_solver: Optional[TwoCaptchaSolver] = None
        self._captcha_solver_init_attempted = False

    def _get_captcha_solver(self) -> Optional[TwoCaptchaSolver]:
        """Lazily initialize the captcha solver if enabled and API key is available."""
        if self._captcha_solver is not None:
            return self._captcha_solver
        if self._captcha_solver_init_attempted:
            return None
        self._captcha_solver_init_attempted = True

        if not self.config.is_captcha_auto_solve_enabled():
            logger.debug("Captcha auto-solve is disabled")
            return None

        api_key = self.config.get_captcha_api_key()
        if not api_key:
            logger.warning("Captcha auto-solve enabled but no API key found in env")
            return None

        provider = self.config.get_captcha_provider()
        if provider.lower() != "2captcha":
            logger.warning("Unsupported captcha provider: %s (only 2captcha supported)", provider)
            return None

        try:
            self._captcha_solver = TwoCaptchaSolver(api_key=api_key)
            logger.info("Captcha solver initialized (provider=%s)", provider)
        except Exception as exc:
            logger.error("Failed to initialize captcha solver: %s", exc)
            return None

        return self._captcha_solver

    def _extract_turnstile_sitekey(self, page: Page) -> Optional[str]:
        """Extract Turnstile sitekey from page if present."""
        selectors = [
            ".cf-turnstile[data-sitekey]",
            "[data-sitekey]",
            "iframe[src*='challenges.cloudflare.com']",
        ]
        for selector in selectors:
            elem = page.query_selector(selector)
            if not elem:
                continue
            sitekey = elem.get_attribute("data-sitekey")
            if sitekey:
                return sitekey.strip()
            if "iframe" in selector:
                src = elem.get_attribute("src") or ""
                import re
                match = re.search(r"sitekey=([^&]+)", src)
                if match:
                    return match.group(1).strip()
        return None

    def _attempt_turnstile_solve(self, page: Page, url: str) -> bool:
        """
        Attempt to solve a Turnstile captcha on the page.
        Returns True if solved and verified, False otherwise.
        """
        solver = self._get_captcha_solver()
        if not solver:
            return False

        sitekey = self._extract_turnstile_sitekey(page)
        if not sitekey:
            logger.info("No Turnstile sitekey found; cannot auto-solve (static Cloudflare page?)")
            return False

        max_attempts = self.config.get_captcha_max_solve_attempts()
        timeout = self.config.get_captcha_solve_timeout_seconds()
        poll_interval = self.config.get_captcha_poll_interval_seconds()

        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(
                    "Attempting Turnstile solve (attempt %s/%s, sitekey=%s...)",
                    attempt, max_attempts, sitekey[:12]
                )
                print(f"\n   🔐 Solving Turnstile captcha (attempt {attempt}/{max_attempts})...")

                token = solver.solve_turnstile(
                    sitekey=sitekey,
                    page_url=url,
                    timeout_seconds=timeout,
                    poll_interval_seconds=poll_interval,
                )

                logger.info("Received Turnstile token (length=%s)", len(token))

                # Inject token into page
                inject_script = """
                    (token) => {
                        // Method 1: Set hidden input
                        const inputs = document.querySelectorAll('input[name="cf-turnstile-response"], input[name="cf_turnstile_response"]');
                        inputs.forEach(input => { input.value = token; });

                        // Method 2: Set turnstile callback data
                        const turnstileDiv = document.querySelector('.cf-turnstile');
                        if (turnstileDiv) {
                            turnstileDiv.setAttribute('data-response', token);
                        }

                        // Method 3: Call turnstile callback if available
                        if (window.turnstile && window.turnstile.getResponse) {
                            try {
                                const widgetId = document.querySelector('.cf-turnstile')?.getAttribute('data-widget-id');
                                if (widgetId) {
                                    window.turnstile.reset(widgetId);
                                }
                            } catch (e) {}
                        }

                        // Method 4: Dispatch event
                        const event = new CustomEvent('turnstile-callback', { detail: { token: token } });
                        document.dispatchEvent(event);

                        return true;
                    }
                """
                page.evaluate(inject_script, token)
                logger.debug("Injected Turnstile token into page")

                # Try to submit the challenge form
                form = page.query_selector("form#challenge-form, form[action*='challenge']")
                if form:
                    submit_btn = form.query_selector("input[type='submit'], button[type='submit']")
                    if submit_btn:
                        submit_btn.click()
                        logger.debug("Clicked challenge form submit button")
                    else:
                        page.evaluate("(form) => form.submit()", form)
                        logger.debug("Submitted challenge form via JS")

                # Wait for navigation or page change
                time.sleep(3)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass

                # Verify captcha is cleared
                if not self._is_captcha_page(page):
                    logger.info("Turnstile captcha solved successfully")
                    print("   ✓ Captcha solved!")
                    return True

                logger.warning("Page still shows captcha after token injection (attempt %s)", attempt)

            except CaptchaSolveError as exc:
                logger.warning("Turnstile solve failed (attempt %s/%s): %s", attempt, max_attempts, exc)
                print(f"   ✗ Solve failed: {exc}")
            except Exception as exc:
                logger.error("Unexpected error during Turnstile solve (attempt %s/%s): %s", attempt, max_attempts, exc)

        logger.warning("All Turnstile solve attempts exhausted")
        return False

    def _random_delay(self) -> None:
        """Add human-like delay between actions"""
        min_delay = self.config.get_min_delay()
        max_delay = self.config.get_max_delay()
        delay = random.uniform(min_delay, max_delay)
        time.sleep(delay)

    def _simulate_human_behavior(self) -> None:
        """Simulate human-like behavior to avoid bot detection"""
        try:
            # Initial delay to let page settle
            time.sleep(random.uniform(2.0, 4.0))

            # Random mouse movements
            for _ in range(random.randint(2, 4)):
                x = random.randint(100, 800)
                y = random.randint(100, 600)
                self.page.mouse.move(x, y)
                time.sleep(random.uniform(0.1, 0.3))

            # Random scroll
            scroll_amount = random.randint(100, 400)
            self.page.evaluate(f'window.scrollBy(0, {scroll_amount})')
            time.sleep(random.uniform(0.3, 0.7))

            # Scroll back up a bit
            scroll_up = random.randint(50, 150)
            self.page.evaluate(f'window.scrollBy(0, -{scroll_up})')
            time.sleep(random.uniform(0.2, 0.5))

            # More mouse movements
            for _ in range(random.randint(1, 3)):
                x = random.randint(200, 1000)
                y = random.randint(150, 500)
                self.page.mouse.move(x, y)
                time.sleep(random.uniform(0.1, 0.2))

            logger.debug("Human behavior simulation completed")
        except Exception as exc:
            logger.debug("Human behavior simulation failed: %s", exc)

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

    def _handle_captcha_prompt(self, page: Page, url: str, *, fetch_kind: str) -> str:
        """
        Handle captcha detection during detail fetches.

        Attempts auto-solve first if enabled and sitekey is present.
        Falls back to policy (abort/skip/pause) if solve fails or isn't possible.

        Returns: "solved", "retry", "skip", or "abort"
        """
        self._log_captcha(url)

        # Attempt auto-solve first
        if self.config.is_captcha_auto_solve_enabled():
            logger.info("Attempting captcha auto-solve for detail %s fetch", fetch_kind)
            if self._attempt_turnstile_solve(page, url):
                self.captcha_consecutive = 0
                return "solved"
            logger.info("Auto-solve failed or not possible; falling back to policy")

        # Auto-solve not available or failed; apply policy
        self._notify_captcha()

        policy = (self.config.get_captcha_on_detect() or "skip").strip().lower()
        if policy not in ("abort", "skip", "pause"):
            logger.warning("Invalid captcha policy %r; defaulting to 'skip'", policy)
            policy = "skip"

        is_tty = False
        try:
            is_tty = bool(sys.stdin.isatty())
        except Exception:
            is_tty = False

        if policy == "pause":
            if not is_tty:
                logger.warning(
                    "Captcha policy is pause but stdin is not interactive; skipping remaining detail fetches"
                )
                policy = "skip"
            else:
                print(f"\n⚠️  CAPTCHA detected during detail {fetch_kind} fetch.")
                print("Solve the captcha in the browser window, then press ENTER to continue.")
                input()
                return "retry"

        if policy == "abort":
            print(
                f"\nCollected {self.total_jobs_collected} jobs with "
                f"{self.total_jobs_with_salary} salaries."
            )
            self.abort_requested = True
            return "abort"

        print(f"\nSkipping remaining detail fetches for this run (captcha policy={policy}).")
        self.skip_detail_fetches = True
        return "skip"


    def _handle_search_captcha(self, page: Page, url: str) -> str:
        """
        Handle captcha detection during search navigation.

        Attempts auto-solve first if enabled and sitekey is present.
        Falls back to policy (abort/skip/pause) if solve fails or isn't possible.

        Returns: "solved", "retry", "skip", or "abort"
        """
        # Attempt auto-solve first
        if self.config.is_captcha_auto_solve_enabled():
            logger.info("Attempting captcha auto-solve for search navigation")
            if self._attempt_turnstile_solve(page, url):
                return "solved"
            logger.info("Auto-solve failed or not possible; falling back to policy")

        # Auto-solve not available or failed; apply policy
        self._notify_captcha()

        policy = (self.config.get_captcha_on_detect() or "skip").strip().lower()
        if policy not in ("abort", "skip", "pause"):
            logger.warning("Invalid captcha policy %r; defaulting to 'skip'", policy)
            policy = "skip"

        is_tty = False
        try:
            is_tty = bool(sys.stdin.isatty())
        except Exception:
            is_tty = False

        if policy == "pause":
            if not is_tty:
                logger.warning(
                    "Captcha policy is pause but stdin is not interactive; skipping this search query"
                )
                policy = "skip"
            else:
                print("\n⚠️  CAPTCHA detected during search navigation.")
                print("Solve the captcha in the browser window, then press ENTER to retry.")
                input()
                return "retry"

        if policy == "abort":
            self.abort_requested = True
            return "abort"

        print("\nSkipping this search query due to captcha.")
        return "skip"

    def _save_search_debug_artifacts(self, page: 'Page', *, label: str) -> Optional[dict]:
        try:
            output_dir = REPO_ROOT / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            stem = f"debug_search_{timestamp}"
            if label:
                stem = f"{stem}_{label}"
            png_path = output_dir / f"{stem}.png"
            html_path = output_dir / f"{stem}.html"
            page.screenshot(path=str(png_path))
            html_path.write_text(page.content(), encoding="utf-8")
            return {"png": str(png_path), "html": str(html_path)}
        except Exception:
            logger.debug("Failed to save search debug artifacts", exc_info=True)
            return None

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

            job_page_selectors = [
                "#jobDescriptionText",
                "div.jobsearch-JobComponent",
                "div#jobsearch-ViewjobPaneWrapper",
                "div.jobsearch-JobInfoHeader-title-container",
            ]
            for selector in job_page_selectors:
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
            body_markers = [
                "verify you are human",
                "additional verification required",
                "please verify you're a human",
            ]
            for marker in body_markers:
                if marker in body:
                    return {"reason": f"body:{marker}", "title": title, "url": url}
            return None
        except Exception:
            return None

    def _fetch_detail_salary(self, url: str) -> tuple[Optional[str], Optional[str]]:
        if not self.context or not url:
            return None, None
        if self.skip_detail_fetches:
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
                    action = self._handle_captcha_prompt(detail_page, url, fetch_kind="salary")
                    if action == "abort":
                        raise CaptchaAbort("User requested abort after captcha")
                    if action == "skip":
                        return None, None
                    if action in ("retry", "solved"):
                        # solved = captcha cleared, continue extraction on same page
                        # retry = user manually solved, re-navigate
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
            "#jobDescriptionText",
            "[data-testid='jobDescriptionText']",
            ".jobsearch-jobDescriptionText",
            "#jobDetailsSection",
            "[data-testid='jobDetailsSection']",
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
                    action = self._handle_captcha_prompt(detail_page, url, fetch_kind="description")
                    if action == "abort":
                        raise CaptchaAbort("User requested abort after captcha")
                    if action == "skip":
                        return None
                    if action in ("retry", "solved"):
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

        # Comprehensive stealth args for headless mode
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

        # Add Indeed-specific init scripts to bypass detection
        try:
            self.page.add_init_script("""
                // Remove webdriver property
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                    configurable: true
                });

                // Add chrome.runtime
                if (!window.chrome) {
                    window.chrome = {};
                }
                window.chrome.runtime = {};

                // Fix navigator.plugins
                Object.defineProperty(navigator, 'plugins', {
                    get: () => {
                        const plugins = [
                            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                            { name: 'Native Client', filename: 'internal-nacl-plugin' }
                        ];
                        plugins.length = 3;
                        return plugins;
                    },
                    configurable: true
                });

                // Fix navigator.languages
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en'],
                    configurable: true
                });

                // Indeed-specific: remove Chromium driver markers
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;

                // Fix permissions API
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                );
            """)
            logger.info("Init scripts added for bot detection bypass")
        except Exception as exc:
            logger.warning("Failed to add init scripts: %s", exc)

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
        results_per_page = 10
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


                captcha_detection = self._is_captcha_page(self.page)
                if captcha_detection:
                    artifacts = self._save_search_debug_artifacts(self.page, label="captcha")
                    logger.warning(
                        "Search page blocked by captcha (reason=%s, title=%s, url=%s, artifacts=%s)",
                        captcha_detection["reason"],
                        captcha_detection["title"],
                        captcha_detection["url"],
                        artifacts,
                    )
                    action = self._handle_search_captcha(self.page, url)
                    logger.warning(
                        "Search captcha action=%s (query=%s, page=%s, url=%s)",
                        action,
                        query,
                        page_index + 1,
                        url,
                    )
                    if action == "abort":
                        raise CaptchaAbort("User requested abort after captcha")
                    if action == "skip":
                        break
                    if action in ("retry", "solved"):
                        # solved = captcha auto-cleared, proceed to extraction
                        # retry = user manually solved, continue loop to re-check
                        if action == "retry":
                            continue
                        # For solved, fall through to extraction

                # Simulate human behavior before interacting with page
                self._simulate_human_behavior()
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

                    captcha_detection = self._is_captcha_page(self.page)

                    if captcha_detection:

                        artifacts = self._save_search_debug_artifacts(self.page, label="captcha")

                        logger.warning(

                            "Search page blocked by captcha after selector failures (reason=%s, title=%s, url=%s, artifacts=%s)",

                            captcha_detection["reason"],

                            captcha_detection["title"],

                            captcha_detection["url"],

                            artifacts,

                        )

                        action = self._handle_search_captcha(self.page, url)

                        logger.warning(

                            "Search captcha action=%s (query=%s, page=%s, url=%s)",

                            action,

                            query,

                            page_index + 1,

                            url,

                        )

                        if action == "abort":

                            raise CaptchaAbort("User requested abort after captcha")

                        if action == "skip":

                            break

                        if action in ("retry", "solved"):

                            continue


                    artifacts = self._save_search_debug_artifacts(self.page, label="no_job_cards")

                    logger.warning(

                        "No job cards found with any selector (query=%s, page=%s, url=%s, artifacts=%s, selectors=%s)",

                        query,

                        page_index + 1,

                        url,

                        artifacts,

                        selectors,

                    )

                    print("   ⚠️  No job cards found - saved debug screenshot + HTML")

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

            external_id = None
            if href:
                external_id = parse_qs(urlparse(href).query).get("jk", [None])[0]
                external_id = external_id.strip() if external_id else None

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
                external_id=external_id,
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
