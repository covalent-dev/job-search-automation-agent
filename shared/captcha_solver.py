import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)


class CaptchaSolveError(RuntimeError):
    pass


class CaptchaSolver:
    """
    High-level captcha solver wrapper for Playwright pages.

    Wraps TwoCaptchaSolver and provides:
    - available() - check if solver is configured
    - solve_if_present(page, detection) - detect captcha type and solve it
    """

    def __init__(self, config: Any):
        self.config = config
        self._solver: Optional["TwoCaptchaSolver"] = None
        self._enabled = False
        self._timeout = 120
        self._max_retries = 2

        captcha_config = {}
        if hasattr(config, "get_captcha_config"):
            captcha_config = config.get_captcha_config() or {}
        elif hasattr(config, "get"):
            captcha_config = config.get("captcha", {}) or {}

        self._enabled = bool(captcha_config.get("enabled", False))
        api_key = (captcha_config.get("api_key") or "").strip()
        self._timeout = int(captcha_config.get("timeout", 120))
        self._max_retries = int(captcha_config.get("max_retries", 2))

        if self._enabled and api_key:
            try:
                self._solver = TwoCaptchaSolver(api_key=api_key)
                logger.info("CaptchaSolver initialized (provider=2captcha)")
            except Exception as e:
                logger.warning("Failed to initialize captcha solver: %s", e)
                self._enabled = False

    def available(self) -> bool:
        """Check if captcha solving is available."""
        return self._enabled and self._solver is not None

    def solve_if_present(self, page: Any, detection: Optional[dict] = None) -> Tuple[bool, str]:
        """
        Attempt to solve a captcha on the given page.

        Args:
            page: Playwright page object
            detection: Optional detection dict with reason/title/url

        Returns:
            Tuple of (solved: bool, reason: str)
        """
        if not self.available():
            return False, "solver_not_available"

        page_url = page.url if page else ""

        # Try to find and extract captcha sitekey
        sitekey = self._extract_sitekey(page)
        captcha_type = self._detect_captcha_type(page, detection)

        if not sitekey:
            logger.warning("Could not extract captcha sitekey from page")
            return False, "no_sitekey_found"

        logger.info("Attempting to solve %s captcha (sitekey=%s...)", captcha_type, sitekey[:16])

        try:
            if captcha_type == "turnstile":
                token = self._solver.solve_turnstile(
                    sitekey=sitekey,
                    page_url=page_url,
                    timeout_seconds=self._timeout,
                )
            elif captcha_type == "hcaptcha":
                token = self._solver.solve_hcaptcha(
                    sitekey=sitekey,
                    page_url=page_url,
                    timeout_seconds=self._timeout,
                )
            elif captcha_type == "recaptcha":
                token = self._solver.solve_recaptcha_v2(
                    sitekey=sitekey,
                    page_url=page_url,
                    timeout_seconds=self._timeout,
                )
            else:
                return False, f"unsupported_captcha_type:{captcha_type}"

            # Inject the token into the page
            injected = self._inject_token(page, token, captcha_type)
            if injected:
                logger.info("Captcha token injected successfully")
                return True, "solved"
            else:
                logger.warning("Failed to inject captcha token")
                return False, "injection_failed"

        except CaptchaSolveError as e:
            logger.warning("Captcha solve failed: %s", e)
            return False, f"solve_error:{e}"
        except Exception as e:
            logger.error("Unexpected error solving captcha: %s", e)
            return False, f"unexpected_error:{e}"

    def _detect_captcha_type(self, page: Any, detection: Optional[dict]) -> str:
        """Detect the type of captcha on the page."""
        try:
            # Check for Cloudflare Turnstile
            if page.query_selector(".cf-turnstile") or page.query_selector("[data-sitekey]"):
                return "turnstile"
            if page.query_selector("iframe[src*='challenges.cloudflare.com']"):
                return "turnstile"

            # Check for hCaptcha
            if page.query_selector("iframe[src*='hcaptcha.com']"):
                return "hcaptcha"
            if page.query_selector(".h-captcha"):
                return "hcaptcha"

            # Check for reCAPTCHA
            if page.query_selector("iframe[src*='recaptcha']"):
                return "recaptcha"
            if page.query_selector(".g-recaptcha"):
                return "recaptcha"

            # Default to turnstile for Cloudflare "Just a moment" pages
            if detection:
                reason = (detection.get("reason") or "").lower()
                title = (detection.get("title") or "").lower()
                if "cloudflare" in reason or "just a moment" in title:
                    return "turnstile"

            return "turnstile"  # Default assumption for Glassdoor
        except Exception:
            return "turnstile"

    def _extract_sitekey(self, page: Any) -> Optional[str]:
        """Extract the captcha sitekey from the page."""
        try:
            # Try data-sitekey attribute (common for Turnstile/hCaptcha)
            elem = page.query_selector("[data-sitekey]")
            if elem:
                sitekey = elem.get_attribute("data-sitekey")
                if sitekey:
                    return sitekey.strip()

            # Try cf-turnstile element
            elem = page.query_selector(".cf-turnstile")
            if elem:
                sitekey = elem.get_attribute("data-sitekey")
                if sitekey:
                    return sitekey.strip()

            # Try h-captcha element
            elem = page.query_selector(".h-captcha")
            if elem:
                sitekey = elem.get_attribute("data-sitekey")
                if sitekey:
                    return sitekey.strip()

            # Try g-recaptcha element
            elem = page.query_selector(".g-recaptcha")
            if elem:
                sitekey = elem.get_attribute("data-sitekey")
                if sitekey:
                    return sitekey.strip()

            # Try to extract from iframe src
            for iframe in page.query_selector_all("iframe"):
                src = iframe.get_attribute("src") or ""
                if "sitekey=" in src:
                    import re
                    match = re.search(r'sitekey=([^&]+)', src)
                    if match:
                        return match.group(1)

            # Try to extract from page scripts
            scripts = page.evaluate("""
                () => {
                    const scripts = document.querySelectorAll('script');
                    for (const s of scripts) {
                        const text = s.textContent || '';
                        const match = text.match(/sitekey['":\\s]+['"]([^'"]+)['"]/i);
                        if (match) return match[1];
                    }
                    return null;
                }
            """)
            if scripts:
                return scripts

            return None
        except Exception as e:
            logger.debug("Error extracting sitekey: %s", e)
            return None

    def _inject_token(self, page: Any, token: str, captcha_type: str) -> bool:
        """Inject the solved captcha token into the page and submit."""
        try:
            if captcha_type == "turnstile":
                # Inject into Turnstile callback or hidden input
                result = page.evaluate("""
                    (token) => {
                        // Try turnstile callback
                        if (window.turnstile && window.turnstile.render) {
                            const widgets = document.querySelectorAll('.cf-turnstile');
                            for (const w of widgets) {
                                const callback = w.getAttribute('data-callback');
                                if (callback && window[callback]) {
                                    window[callback](token);
                                    return true;
                                }
                            }
                        }
                        // Try hidden input
                        const input = document.querySelector('input[name="cf-turnstile-response"]') ||
                                     document.querySelector('input[name="g-recaptcha-response"]');
                        if (input) {
                            input.value = token;
                            // Try to submit the form
                            const form = input.closest('form');
                            if (form) {
                                form.submit();
                                return true;
                            }
                        }
                        // Try direct callback
                        if (window.__cfCallback) {
                            window.__cfCallback(token);
                            return true;
                        }
                        return false;
                    }
                """, token)
                return bool(result)

            elif captcha_type in ("hcaptcha", "recaptcha"):
                result = page.evaluate("""
                    (token) => {
                        const input = document.querySelector('textarea[name="h-captcha-response"]') ||
                                     document.querySelector('textarea[name="g-recaptcha-response"]') ||
                                     document.querySelector('input[name="g-recaptcha-response"]');
                        if (input) {
                            input.value = token;
                            const form = input.closest('form');
                            if (form) {
                                form.submit();
                                return true;
                            }
                        }
                        // Try callback
                        if (window.hcaptcha && window.hcaptcha.execute) {
                            return true;
                        }
                        if (window.grecaptcha && window.grecaptcha.execute) {
                            return true;
                        }
                        return false;
                    }
                """, token)
                return bool(result)

            return False
        except Exception as e:
            logger.warning("Error injecting captcha token: %s", e)
            return False


class TwoCaptchaSolver:
    """
    Minimal 2captcha wrapper for Turnstile.

    Notes:
      - Never logs API keys or tokens.
      - Uses 2captcha HTTP API via urllib (no extra dependencies).
    """

    provider = "2captcha"

    def __init__(self, api_key: str, base_url: str = "https://2captcha.com"):
        api_key = (api_key or "").strip()
        if not api_key:
            raise ValueError("2captcha api_key is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    def solve_turnstile(
        self,
        *,
        sitekey: str,
        page_url: str,
        user_agent: Optional[str] = None,
        action: Optional[str] = None,
        data: Optional[str] = None,
        timeout_seconds: int = 180,
        poll_interval_seconds: int = 5,
    ) -> str:
        sitekey = (sitekey or "").strip()
        page_url = (page_url or "").strip()
        if not sitekey:
            raise ValueError("turnstile sitekey is required")
        if not page_url:
            raise ValueError("turnstile page_url is required")

        request_id = self._submit_turnstile(
            sitekey=sitekey,
            page_url=page_url,
            user_agent=user_agent,
            action=action,
            data=data,
        )

        return self._poll_until_solved(
            request_id=request_id,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

    def solve_hcaptcha(
        self,
        *,
        sitekey: str,
        page_url: str,
        timeout_seconds: int = 180,
        poll_interval_seconds: int = 5,
    ) -> str:
        sitekey = (sitekey or "").strip()
        page_url = (page_url or "").strip()
        if not sitekey:
            raise ValueError("hcaptcha sitekey is required")
        if not page_url:
            raise ValueError("hcaptcha page_url is required")

        request_id = self._submit_hcaptcha(sitekey=sitekey, page_url=page_url)
        return self._poll_until_solved(
            request_id=request_id,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

    def solve_recaptcha_v2(
        self,
        *,
        sitekey: str,
        page_url: str,
        invisible: Optional[bool] = None,
        timeout_seconds: int = 180,
        poll_interval_seconds: int = 5,
    ) -> str:
        sitekey = (sitekey or "").strip()
        page_url = (page_url or "").strip()
        if not sitekey:
            raise ValueError("recaptcha sitekey is required")
        if not page_url:
            raise ValueError("recaptcha page_url is required")

        request_id = self._submit_recaptcha_v2(
            sitekey=sitekey,
            page_url=page_url,
            invisible=invisible,
        )
        return self._poll_until_solved(
            request_id=request_id,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

    def _poll_until_solved(
        self,
        *,
        request_id: str,
        timeout_seconds: int,
        poll_interval_seconds: int,
    ) -> str:
        deadline = time.monotonic() + max(int(timeout_seconds), 1)
        poll_interval = max(float(poll_interval_seconds), 1.0)

        while time.monotonic() < deadline:
            token = self._poll_result(request_id=request_id)
            if token is not None:
                token = token.strip()
                if not token:
                    raise CaptchaSolveError("2captcha returned empty token")
                return token
            time.sleep(poll_interval)

        raise CaptchaSolveError("2captcha timed out waiting for solution")

    def _submit_turnstile(
        self,
        *,
        sitekey: str,
        page_url: str,
        user_agent: Optional[str],
        action: Optional[str],
        data: Optional[str],
    ) -> str:
        payload = {
            "key": self._api_key,
            "method": "turnstile",
            "sitekey": sitekey,
            "pageurl": page_url,
            "json": 1,
        }
        if user_agent:
            payload["userAgent"] = user_agent
        if action:
            payload["action"] = action
        if data:
            payload["data"] = data

        resp = self._post_json("/in.php", payload)
        if resp.get("status") != 1:
            raise CaptchaSolveError(f"2captcha submit error: {resp.get('request')}")
        request_id = (resp.get("request") or "").strip()
        if not request_id:
            raise CaptchaSolveError("2captcha submit returned empty request id")
        return request_id

    def _submit_hcaptcha(self, *, sitekey: str, page_url: str) -> str:
        payload = {
            "key": self._api_key,
            "method": "hcaptcha",
            "sitekey": sitekey,
            "pageurl": page_url,
            "json": 1,
        }
        resp = self._post_json("/in.php", payload)
        if resp.get("status") != 1:
            raise CaptchaSolveError(f"2captcha submit error: {resp.get('request')}")
        request_id = (resp.get("request") or "").strip()
        if not request_id:
            raise CaptchaSolveError("2captcha submit returned empty request id")
        return request_id

    def _submit_recaptcha_v2(
        self,
        *,
        sitekey: str,
        page_url: str,
        invisible: Optional[bool],
    ) -> str:
        payload = {
            "key": self._api_key,
            "method": "userrecaptcha",
            "googlekey": sitekey,
            "pageurl": page_url,
            "json": 1,
        }
        if invisible is True:
            payload["invisible"] = 1
        resp = self._post_json("/in.php", payload)
        if resp.get("status") != 1:
            raise CaptchaSolveError(f"2captcha submit error: {resp.get('request')}")
        request_id = (resp.get("request") or "").strip()
        if not request_id:
            raise CaptchaSolveError("2captcha submit returned empty request id")
        return request_id

    def _poll_result(self, *, request_id: str) -> Optional[str]:
        params = {
            "key": self._api_key,
            "action": "get",
            "id": request_id,
            "json": 1,
        }
        resp = self._get_json("/res.php", params)
        status = resp.get("status")
        value = (resp.get("request") or "").strip()
        if status == 1:
            return value
        if value == "CAPCHA_NOT_READY":
            return None
        raise CaptchaSolveError(f"2captcha poll error: {value}")

    def _post_json(self, path: str, payload: dict) -> dict:
        url = f"{self._base_url}{path}"
        body = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8", errors="replace")
        return self._parse_json(text)

    def _get_json(self, path: str, params: dict) -> dict:
        url = f"{self._base_url}{path}?{urllib.parse.urlencode(params)}"
        with urllib.request.urlopen(url, timeout=30) as resp:
            text = resp.read().decode("utf-8", errors="replace")
        return self._parse_json(text)

    def _parse_json(self, text: str) -> dict:
        try:
            data = json.loads(text)
        except Exception as exc:
            raise CaptchaSolveError("2captcha returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise CaptchaSolveError("2captcha returned unexpected response shape")
        return data
