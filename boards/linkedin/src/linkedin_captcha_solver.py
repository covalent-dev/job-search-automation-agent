"""
LinkedIn captcha solver integration for the collector.

Bridges the shared TwoCaptchaSolver with LinkedIn-specific captcha handling.
Supports Cloudflare Turnstile challenges commonly seen on LinkedIn.
"""

import importlib.util
import logging
import random
import time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

if TYPE_CHECKING:
    from playwright.sync_api import Page

# Load shared captcha_solver module explicitly to avoid naming conflict
_shared_module_path = Path(__file__).resolve().parents[3] / "shared" / "captcha_solver.py"
_spec = importlib.util.spec_from_file_location("shared_captcha_solver", _shared_module_path)
_shared_captcha = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shared_captcha)

TwoCaptchaSolver = _shared_captcha.TwoCaptchaSolver
CaptchaSolveError = _shared_captcha.CaptchaSolveError

logger = logging.getLogger(__name__)


def is_solver_configured(config) -> bool:
    """
    Check if captcha auto-solving is enabled and properly configured.

    Returns True only if:
    - captcha.enabled or captcha.auto_solve is True in config
    - CAPTCHA_API_KEY env var is set and non-empty
    - Provider is supported (currently only 2captcha)
    """
    if not config.is_captcha_auto_solve_enabled():
        return False

    api_key = config.get_captcha_api_key()
    if not api_key:
        logger.debug("Captcha solver disabled: no API key configured")
        return False

    provider = config.get_captcha_provider()
    if provider.lower() != "2captcha":
        logger.warning("Unsupported captcha provider: %s (only 2captcha supported)", provider)
        return False

    return True


def _extract_turnstile_sitekey(page: "Page") -> str | None:
    """Extract Cloudflare Turnstile sitekey from page."""
    # Check for cf-turnstile widget
    selectors = [
        ".cf-turnstile[data-sitekey]",
        "div.cf-turnstile-wrapper",
        "iframe[src*='challenges.cloudflare.com']",
    ]

    for selector in selectors:
        elem = page.query_selector(selector)
        if elem:
            sitekey = elem.get_attribute("data-sitekey")
            if sitekey:
                return sitekey.strip()
            src = elem.get_attribute("src") or ""
            if src:
                try:
                    qs = parse_qs(urlparse(src).query)
                    value = (qs.get("k", [None])[0] or qs.get("sitekey", [None])[0] or "").strip()
                    if value:
                        return value
                except Exception:
                    pass

    # Try to find sitekey in page source
    try:
        content = page.content()
        import re
        # Look for turnstile sitekey patterns
        patterns = [
            r'cf-turnstile[^>]*data-sitekey=["\']([^"\']+)["\']',
            r'turnstileSiteKey["\']?\s*[:=]\s*["\']([^"\']+)["\']',
            r'turnstile[^\\n]{0,80}sitekey["\']?\s*[:=]\s*["\']([^"\']+)["\']',
        ]
        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                return match.group(1).strip()
    except Exception:
        pass

    return None


def _extract_hcaptcha_sitekey(page: "Page") -> str | None:
    selectors = [
        ".h-captcha[data-sitekey]",
        "[data-sitekey][data-callback][class*='hcaptcha']",
        "iframe[src*='hcaptcha.com']",
    ]
    for selector in selectors:
        elem = page.query_selector(selector)
        if not elem:
            continue
        sitekey = elem.get_attribute("data-sitekey")
        if sitekey:
            return sitekey.strip()
        src = elem.get_attribute("src") or ""
        if src:
            try:
                qs = parse_qs(urlparse(src).query)
                value = (qs.get("sitekey", [None])[0] or "").strip()
                if value:
                    return value
            except Exception:
                pass
    return None


def _extract_recaptcha_sitekey(page: "Page") -> str | None:
    selectors = [
        ".g-recaptcha[data-sitekey]",
        "[data-sitekey][class*='recaptcha']",
        "iframe[src*='recaptcha']",
    ]
    for selector in selectors:
        elem = page.query_selector(selector)
        if not elem:
            continue
        sitekey = elem.get_attribute("data-sitekey")
        if sitekey:
            return sitekey.strip()
        src = elem.get_attribute("src") or ""
        if src:
            try:
                qs = parse_qs(urlparse(src).query)
                value = (qs.get("k", [None])[0] or "").strip()
                if value:
                    return value
            except Exception:
                pass
    return None


def _detect_captcha(page: "Page") -> tuple[str, str] | None:
    sitekey = _extract_turnstile_sitekey(page)
    if sitekey:
        return ("turnstile", sitekey)
    sitekey = _extract_hcaptcha_sitekey(page)
    if sitekey:
        return ("hcaptcha", sitekey)
    sitekey = _extract_recaptcha_sitekey(page)
    if sitekey:
        return ("recaptcha_v2", sitekey)
    return None


def _inject_turnstile_token(page: "Page", token: str) -> bool:
    """Inject solved Turnstile token into the page."""
    try:
        # Method 1: Set value on cf-turnstile-response input
        response_selectors = [
            "input[name='cf-turnstile-response']",
            "[name='cf-turnstile-response']",
            "input.cf-turnstile-response",
        ]
        for selector in response_selectors:
            elem = page.query_selector(selector)
            if elem:
                page.evaluate(
                    """(args) => {
                        const elem = document.querySelector(args.selector);
                        if (elem) {
                            elem.value = args.token;
                            return true;
                        }
                        return false;
                    }""",
                    {"selector": selector, "token": token}
                )
                logger.debug("Injected token via selector: %s", selector)
                return True

        # Method 2: Set via turnstile callback if available
        injected = page.evaluate(
            """(token) => {
                // Try setting directly on any hidden turnstile input
                const inputs = document.querySelectorAll('input[type="hidden"]');
                for (const input of inputs) {
                    if (input.name && input.name.toLowerCase().includes('turnstile')) {
                        input.value = token;
                        return true;
                    }
                }
                // Try calling turnstile callback
                if (window.turnstile && window.turnstile.render) {
                    // Some pages expose a callback
                    const widgets = document.querySelectorAll('.cf-turnstile');
                    for (const widget of widgets) {
                        const callback = widget.getAttribute('data-callback');
                        if (callback && typeof window[callback] === 'function') {
                            window[callback](token);
                            return true;
                        }
                    }
                }
                return false;
            }""",
            token
        )
        if injected:
            logger.debug("Injected token via JavaScript callback")
            return True

        # Method 3: Create the input if it doesn't exist
        page.evaluate(
            """(token) => {
                let input = document.querySelector('input[name="cf-turnstile-response"]');
                if (!input) {
                    input = document.createElement('input');
                    input.type = 'hidden';
                    input.name = 'cf-turnstile-response';
                    const form = document.querySelector('form');
                    if (form) {
                        form.appendChild(input);
                    } else {
                        document.body.appendChild(input);
                    }
                }
                input.value = token;
            }""",
            token
        )
        logger.debug("Created and set cf-turnstile-response input")
        return True

    except Exception as exc:
        logger.warning("Failed to inject turnstile token: %s", exc)
        return False


def _inject_response_token(page: "Page", *, name: str, token: str) -> bool:
    try:
        ok = page.evaluate(
            """(args) => {
                const {name, token} = args;
                const selector = `textarea[name="${name}"], input[name="${name}"]`;
                let el = document.querySelector(selector);
                if (!el) {
                    // reCAPTCHA/hCaptcha usually expects a textarea
                    el = document.createElement('textarea');
                    el.name = name;
                    el.style.display = 'none';
                    document.body.appendChild(el);
                }
                el.value = token;
                el.innerHTML = token;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                return true;
            }""",
            {"name": name, "token": token},
        )
        return bool(ok)
    except Exception as exc:
        logger.warning("Failed to inject %s token: %s", name, exc)
        return False


def _try_invoke_data_callback(page: "Page", token: str) -> None:
    try:
        page.evaluate(
            """(token) => {
                const candidates = document.querySelectorAll('[data-callback]');
                for (const el of candidates) {
                    const cb = el.getAttribute('data-callback');
                    if (cb && typeof window[cb] === 'function') {
                        try { window[cb](token); } catch (e) {}
                    }
                }
            }""",
            token,
        )
    except Exception:
        pass


def maybe_solve_and_inject(page: "Page", config, *, context: str = "") -> bool:
    """
    Attempt to solve a captcha on the page and inject the response.

    Args:
        page: Playwright page with a captcha challenge
        config: ConfigLoader instance with captcha settings
        context: Description of where captcha was encountered (for logging)

    Returns:
        True if captcha was solved and token injected, False otherwise
    """
    if not is_solver_configured(config):
        return False

    page_url = page.url
    detected = _detect_captcha(page)
    if not detected:
        logger.info("No supported captcha detected on page (context=%s)", context)
        return False
    kind, sitekey = detected

    logger.info(
        "Attempting %s solve (context=%s, url=%s)",
        kind,
        context,
        page_url[:80] + "..." if len(page_url) > 80 else page_url,
    )

    api_key = config.get_captcha_api_key()
    timeout = config.get_captcha_solve_timeout_seconds()
    poll_interval = config.get_captcha_poll_interval_seconds()
    max_attempts = config.get_captcha_max_solve_attempts()

    # Get user agent from page if possible
    user_agent = None
    try:
        user_agent = page.evaluate("() => navigator.userAgent")
    except Exception:
        pass

    solver = TwoCaptchaSolver(api_key=api_key)

    for attempt in range(1, max_attempts + 1):
        try:
            logger.info("Captcha solve attempt %d/%d", attempt, max_attempts)
            if kind == "turnstile":
                token = solver.solve_turnstile(
                    sitekey=sitekey,
                    page_url=page_url,
                    user_agent=user_agent,
                    timeout_seconds=timeout,
                    poll_interval_seconds=poll_interval,
                )
            elif kind == "hcaptcha":
                token = solver.solve_hcaptcha(
                    sitekey=sitekey,
                    page_url=page_url,
                    timeout_seconds=timeout,
                    poll_interval_seconds=poll_interval,
                )
            elif kind == "recaptcha_v2":
                token = solver.solve_recaptcha_v2(
                    sitekey=sitekey,
                    page_url=page_url,
                    timeout_seconds=timeout,
                    poll_interval_seconds=poll_interval,
                )
            else:
                logger.warning("Unsupported captcha kind: %s", kind)
                return False

            if not token:
                logger.warning("Solver returned empty token (attempt %d)", attempt)
                continue

            injected = False
            if kind == "turnstile":
                injected = _inject_turnstile_token(page, token)
            elif kind == "hcaptcha":
                injected = _inject_response_token(page, name="h-captcha-response", token=token)
                injected = _inject_response_token(page, name="g-recaptcha-response", token=token) or injected
            elif kind == "recaptcha_v2":
                injected = _inject_response_token(page, name="g-recaptcha-response", token=token)

            if injected:
                _try_invoke_data_callback(page, token)
                logger.info("Captcha solved and token injected successfully (kind=%s)", kind)
                return True

            logger.warning("Failed to inject token (attempt %d)", attempt)

        except CaptchaSolveError as exc:
            logger.warning("Captcha solve failed (attempt %d): %s", attempt, exc)
        except Exception as exc:
            logger.warning("Unexpected error during captcha solve (attempt %d): %s", attempt, exc)
        if attempt < max_attempts:
            sleep_seconds = min(5 * (2 ** (attempt - 1)), 30) + random.uniform(0, 1.5)
            logger.info("Waiting %.1fs before retrying captcha solve", sleep_seconds)
            time.sleep(sleep_seconds)

    logger.warning("All captcha solve attempts exhausted")
    return False
