"""
Cloudflare bypass utilities for Playwright-based scrapers.

Provides:
- Enhanced stealth arguments and scripts
- Human-like behavior simulation
- Session persistence helpers
- Optional FlareSolverr integration
"""

import logging
import random
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Browser launch arguments for stealth
STEALTH_ARGS: List[str] = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-site-isolation-trials",
    "--disable-web-security",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-accelerated-2d-canvas",
    "--disable-gpu",
    "--window-size=1920,1080",
    "--start-maximized",
    "--hide-scrollbars",
    "--mute-audio",
    "--disable-infobars",
    "--disable-notifications",
    "--disable-popup-blocking",
    "--ignore-certificate-errors",
    "--allow-running-insecure-content",
    "--no-first-run",
    "--no-default-browser-check",
]


# JavaScript to inject for stealth (comprehensive anti-detection)
STEALTH_INIT_SCRIPT: str = """
// Overwrite navigator.webdriver
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
});

// Add chrome runtime object
window.chrome = {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: {},
};

// Fix plugins to look realistic
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
            { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
        ];
        plugins.item = (i) => plugins[i] || null;
        plugins.namedItem = (name) => plugins.find(p => p.name === name) || null;
        plugins.refresh = () => {};
        return plugins;
    },
});

// Fix languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
});

// Fix platform
Object.defineProperty(navigator, 'platform', {
    get: () => 'Win32',
});

// Fix hardware concurrency
Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => 8,
});

// Fix device memory
Object.defineProperty(navigator, 'deviceMemory', {
    get: () => 8,
});

// Override permissions query
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);

// Fix WebGL vendor/renderer
const getParameterProxyHandler = {
    apply: function(target, thisArg, args) {
        const param = args[0];
        const gl = thisArg;
        if (param === 37445) {
            return 'Intel Inc.';
        }
        if (param === 37446) {
            return 'Intel Iris OpenGL Engine';
        }
        return Reflect.apply(target, thisArg, args);
    }
};

try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
    if (gl) {
        gl.getParameter = new Proxy(gl.getParameter, getParameterProxyHandler);
    }
    const gl2 = canvas.getContext('webgl2');
    if (gl2) {
        gl2.getParameter = new Proxy(gl2.getParameter, getParameterProxyHandler);
    }
} catch (e) {}

// Prevent detection via iframe contentWindow
try {
    const iframeDescriptor = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentWindow');
    Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
        get: function() {
            const iframe = iframeDescriptor.get.call(this);
            if (!iframe) return iframe;
            try {
                if (iframe.navigator && iframe.navigator.webdriver !== undefined) {
                    Object.defineProperty(iframe.navigator, 'webdriver', { get: () => undefined });
                }
            } catch (e) {}
            return iframe;
        }
    });
} catch (e) {}

// Override Date to avoid timezone detection
const originalDate = Date;
class ModifiedDate extends originalDate {
    constructor(...args) {
        if (args.length === 0) {
            super();
        } else {
            super(...args);
        }
    }
    getTimezoneOffset() {
        return 300; // EST timezone offset
    }
}
// Don't replace Date globally as it can break sites, but prepare for targeted use
"""


class CloudflareBypass:
    """
    Centralized Cloudflare bypass utilities.

    Usage:
        bypass = CloudflareBypass(config)
        bypass.apply_stealth_to_page(page)
        bypass.human_like_warmup(page)
        success = bypass.wait_for_challenge(page)
    """

    def __init__(self, config: Any = None):
        self.config = config
        self._load_config()

    def _load_config(self) -> None:
        """Load Cloudflare bypass configuration."""
        cf_config = {}
        if self.config:
            if hasattr(self.config, "get"):
                cf_config = self.config.get("cloudflare", {}) or {}

        self.enabled = bool(cf_config.get("enabled", True))
        self.min_delay = float(cf_config.get("min_delay_between_queries", 3.0))
        self.max_delay = float(cf_config.get("max_delay_between_queries", 8.0))
        self.warmup_delay = float(cf_config.get("warmup_delay", 2.0))
        self.jitter_factor = float(cf_config.get("jitter_factor", 0.3))
        self.session_persistence = bool(cf_config.get("session_persistence", True))
        self.turnstile_solving = bool(cf_config.get("turnstile_solving", True))

        # Backwards-compat: older configs stored FlareSolverr URL under cloudflare.flaresolverr_url
        legacy_url = (cf_config.get("flaresolverr_url") or "").strip()

        fs_config: Dict[str, Any] = {}
        if self.config and hasattr(self.config, "get"):
            fs_config = self.config.get("flaresolverr", {}) or {}

        self.flaresolverr_enabled = bool(fs_config.get("enabled", False))
        self.flaresolverr_url = (fs_config.get("url") or legacy_url or "").strip()
        self.flaresolverr_timeout = int(fs_config.get("timeout", 60) or 60)

    def get_stealth_args(self) -> List[str]:
        """Get browser launch arguments for stealth mode."""
        return STEALTH_ARGS.copy()

    def get_stealth_script(self) -> str:
        """Get JavaScript to inject for stealth."""
        return STEALTH_INIT_SCRIPT

    def apply_stealth_to_page(self, page: Any) -> None:
        """Apply stealth measures to a Playwright page."""
        if not self.enabled:
            return

        try:
            page.add_init_script(STEALTH_INIT_SCRIPT)
            logger.debug("Stealth init script added to page")
        except Exception as e:
            logger.warning("Failed to add stealth init script: %s", e)

        # Try to apply playwright_stealth if available
        try:
            from playwright_stealth.stealth import Stealth
            Stealth().apply_stealth_sync(page)
            logger.debug("Playwright-stealth applied to page")
        except ImportError:
            logger.debug("playwright_stealth not installed, using built-in stealth only")
        except Exception as e:
            logger.warning("Failed to apply playwright-stealth: %s", e)

    def apply_stealth_to_context(self, context: Any) -> None:
        """Apply stealth measures to all new pages in a context."""
        if not self.enabled:
            return

        try:
            context.add_init_script(STEALTH_INIT_SCRIPT)
            logger.debug("Stealth init script added to context")
        except Exception as e:
            logger.warning("Failed to add stealth to context: %s", e)

    def human_delay(self, min_s: Optional[float] = None, max_s: Optional[float] = None) -> float:
        """
        Add human-like delay with jitter.

        Args:
            min_s: Minimum delay (defaults to config)
            max_s: Maximum delay (defaults to config)

        Returns:
            The actual delay in seconds
        """
        min_delay = min_s if min_s is not None else self.min_delay
        max_delay = max_s if max_s is not None else self.max_delay

        base = random.uniform(min_delay, max_delay)
        jitter = base * self.jitter_factor
        delay = base + random.uniform(-jitter, jitter)
        delay = max(0.5, delay)

        time.sleep(delay)
        return delay

    def human_like_warmup(self, page: Any) -> None:
        """
        Perform human-like warmup actions on a page.

        This helps establish a "normal" browser fingerprint before scraping.
        """
        if not self.enabled:
            return

        try:
            # Initial delay
            time.sleep(random.uniform(self.warmup_delay, self.warmup_delay + 2))

            # Random mouse movements
            page.mouse.move(random.randint(100, 500), random.randint(100, 300))
            time.sleep(random.uniform(0.3, 0.8))
            page.mouse.move(random.randint(200, 600), random.randint(200, 400))
            time.sleep(random.uniform(0.2, 0.5))

            # Scroll slightly
            page.evaluate("window.scrollBy(0, %d)" % random.randint(50, 150))
            time.sleep(random.uniform(0.5, 1.0))

            # Maybe scroll back up
            if random.random() > 0.5:
                page.evaluate("window.scrollBy(0, %d)" % random.randint(-100, -30))
                time.sleep(random.uniform(0.3, 0.7))

            logger.debug("Human-like warmup completed")
        except Exception as e:
            logger.debug("Human-like warmup failed (non-critical): %s", e)

    def is_cloudflare_challenge(self, page: Any) -> Optional[Dict[str, str]]:
        """
        Check if page is showing a Cloudflare challenge.

        Returns:
            Detection dict with reason/title/url if challenge detected, None otherwise
        """
        try:
            title = (page.title() or "").lower()
            url = (page.url or "").lower()

            # Title-based detection
            title_markers = [
                "just a moment...",
                "attention required! | cloudflare",
                "please wait...",
                "checking your browser",
            ]
            for marker in title_markers:
                if marker in title:
                    return {"reason": f"title:{marker}", "title": title, "url": url}

            # URL-based detection
            url_markers = [
                "__cf_chl",
                "/cdn-cgi/",
                "challenges.cloudflare.com",
                "cf-challenge",
            ]
            for marker in url_markers:
                if marker in url:
                    return {"reason": f"url:{marker}", "title": title, "url": url}

            # Selector-based detection
            selector_markers = {
                "#cf-challenge-running": "selector:#cf-challenge-running",
                "form#challenge-form": "selector:form#challenge-form",
                "iframe[src*='challenges.cloudflare.com']": "selector:cloudflare-iframe",
                ".cf-turnstile": "selector:cf-turnstile",
            }
            for selector, reason in selector_markers.items():
                if page.query_selector(selector):
                    return {"reason": reason, "title": title, "url": url}

            # Body text detection
            body = (page.inner_text("body") or "").lower()
            body_markers = [
                "verify you are human",
                "additional verification required",
                "please verify you're a human",
                "checking your browser before accessing",
            ]
            for marker in body_markers:
                if marker in body:
                    return {"reason": f"body:{marker}", "title": title, "url": url}

            return None
        except Exception:
            return None

    def wait_for_challenge(
        self,
        page: Any,
        timeout_seconds: int = 30,
        poll_interval: float = 1.0,
    ) -> bool:
        """
        Wait for Cloudflare challenge to complete automatically.

        Some JS challenges auto-complete after a few seconds.

        Args:
            page: Playwright page
            timeout_seconds: Maximum wait time
            poll_interval: Time between checks

        Returns:
            True if challenge cleared, False if still blocked
        """
        import time

        deadline = time.monotonic() + timeout_seconds
        logger.info("Waiting for Cloudflare challenge to complete...")

        while time.monotonic() < deadline:
            detection = self.is_cloudflare_challenge(page)
            if detection is None:
                logger.info("Cloudflare challenge cleared")
                return True

            time.sleep(poll_interval)

        logger.warning("Cloudflare challenge did not clear within timeout")
        return False

    def get_flaresolverr(self):
        """
        Return a configured FlareSolverr client if enabled, else None.

        Callers must still check availability via client.is_available().
        """
        if not self.flaresolverr_enabled or not self.flaresolverr_url:
            return None

        try:
            from flaresolverr import FlareSolverr
        except Exception:
            return None

        return FlareSolverr(url=self.flaresolverr_url, timeout=self.flaresolverr_timeout)

    @staticmethod
    def _user_agent_override_script(user_agent: str) -> str:
        ua = user_agent.replace("\\", "\\\\").replace("'", "\\'")
        return (
            "Object.defineProperty(navigator, 'userAgent', {get: () => '" + ua + "'});\n"
            "Object.defineProperty(navigator, 'appVersion', {get: () => '" + ua + "'});\n"
        )

    def inject_flaresolverr_solution(self, context: Any, *, cookies: List[Dict[str, Any]], user_agent: str) -> None:
        """
        Inject FlareSolverr solution into a Playwright context.

        Best-effort:
        - Adds cookies to context
        - Aligns User-Agent via extra headers + navigator override
        """
        try:
            from flaresolverr import flaresolverr_cookies_to_playwright

            pw_cookies = flaresolverr_cookies_to_playwright(cookies)
            if pw_cookies:
                context.add_cookies(pw_cookies)
        except Exception as exc:
            logger.debug("Failed to inject FlareSolverr cookies (non-critical): %s", exc)

        if user_agent:
            try:
                context.set_extra_http_headers({"User-Agent": user_agent})
            except Exception:
                pass
            try:
                context.add_init_script(self._user_agent_override_script(user_agent))
            except Exception:
                pass
