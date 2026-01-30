"""

Configuration loader for Job Bot
Reads and validates settings.yaml
"""

import yaml
import os
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ConfigValidationError(ValueError):
    """Raised when configuration fails invariant validation."""
    pass


def _validate_non_negative(value: Any, field: str) -> None:
    """Validate that a numeric value is non-negative."""
    if value is not None and float(value) < 0:
        raise ConfigValidationError(
            f"Invalid config: '{field}' must be non-negative, got {value}"
        )


def _validate_positive(value: Any, field: str) -> None:
    """Validate that a numeric value is positive (> 0)."""
    if value is not None and float(value) <= 0:
        raise ConfigValidationError(
            f"Invalid config: '{field}' must be positive (> 0), got {value}"
        )


def _validate_min_max_pair(min_val: Any, max_val: Any, min_field: str, max_field: str) -> None:
    """Validate that min_val <= max_val for a delay/range pair."""
    if min_val is not None and max_val is not None:
        if float(min_val) > float(max_val):
            raise ConfigValidationError(
                f"Invalid config: '{min_field}' ({min_val}) must be <= '{max_field}' ({max_val})"
            )


class ConfigLoader:
    """Loads and validates configuration from YAML file"""
    
    def __init__(self, config_path: str = "config/settings.yaml"):
        self.config_path = Path(config_path)
        self.config: Dict[str, Any] = {}
        self._load()
    
    def _load(self) -> None:
        """Load config from YAML file"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        try:
            with open(self.config_path, 'r') as f:
                self.config = yaml.safe_load(f)
            logger.info(f"✓ Config loaded from {self.config_path}")
        except yaml.YAMLError as e:
            logger.error(f"Error parsing config file: {e}")
            raise

        self._validate_invariants()

    def _validate_invariants(self) -> None:
        """Validate configuration invariants. Raises ConfigValidationError on failure."""
        # Browser delay range
        min_delay = self.get('browser.min_delay')
        max_delay = self.get('browser.max_delay')
        _validate_non_negative(min_delay, 'browser.min_delay')
        _validate_non_negative(max_delay, 'browser.max_delay')
        _validate_min_max_pair(min_delay, max_delay, 'browser.min_delay', 'browser.max_delay')

        # Browser timeouts (must be positive)
        _validate_positive(self.get('browser.page_timeout'), 'browser.page_timeout')
        _validate_positive(self.get('browser.navigation_timeout'), 'browser.navigation_timeout')
        _validate_positive(self.get('browser.launch_timeout'), 'browser.launch_timeout')

        # Browser retries (non-negative)
        _validate_non_negative(self.get('browser.max_retries'), 'browser.max_retries')

        # Detail salary fetch settings
        salary_delay_min = self.get('search.detail_salary_delay_min')
        salary_delay_max = self.get('search.detail_salary_delay_max')
        _validate_non_negative(salary_delay_min, 'search.detail_salary_delay_min')
        _validate_non_negative(salary_delay_max, 'search.detail_salary_delay_max')
        _validate_min_max_pair(
            salary_delay_min, salary_delay_max,
            'search.detail_salary_delay_min', 'search.detail_salary_delay_max'
        )
        _validate_positive(self.get('search.detail_salary_timeout'), 'search.detail_salary_timeout')
        _validate_non_negative(self.get('search.detail_salary_retries'), 'search.detail_salary_retries')
        _validate_non_negative(self.get('search.detail_salary_max_per_query'), 'search.detail_salary_max_per_query')

        # Detail description fetch settings
        desc_delay_min = self.get('search.detail_description_delay_min')
        desc_delay_max = self.get('search.detail_description_delay_max')
        _validate_non_negative(desc_delay_min, 'search.detail_description_delay_min')
        _validate_non_negative(desc_delay_max, 'search.detail_description_delay_max')
        _validate_min_max_pair(
            desc_delay_min, desc_delay_max,
            'search.detail_description_delay_min', 'search.detail_description_delay_max'
        )
        _validate_positive(self.get('search.detail_description_timeout'), 'search.detail_description_timeout')
        _validate_non_negative(self.get('search.detail_description_retries'), 'search.detail_description_retries')
        _validate_non_negative(self.get('search.detail_description_max_per_query'), 'search.detail_description_max_per_query')

        # Search limits (non-negative)
        _validate_non_negative(self.get('search.max_results_per_search'), 'search.max_results_per_search')
        _validate_non_negative(self.get('search.max_pages'), 'search.max_pages')

        # AI filter settings
        _validate_non_negative(self.get('ai_filter.max_retries'), 'ai_filter.max_retries')
        _validate_non_negative(self.get('ai_filter.max_reasoning_chars'), 'ai_filter.max_reasoning_chars')

        # Captcha settings
        _validate_positive(self.get('captcha.solve_timeout_seconds') or self.get('captcha.timeout'), 'captcha.solve_timeout_seconds')
        _validate_non_negative(self.get('captcha.max_solve_attempts') or self.get('captcha.max_retries'), 'captcha.max_solve_attempts')

        # Proxy settings (validated only when enabled)
        if self.is_proxy_enabled():
            try:
                _ = self.get_playwright_proxy()
            except Exception as exc:
                raise ConfigValidationError(str(exc)) from exc
            _validate_positive(self.get_proxy_pool_size(), 'browser.proxy.pool_size')
            _validate_non_negative(self.get_proxy_session_ttl_seconds(), 'browser.proxy.session_ttl_seconds')

        logger.debug("✓ Config invariants validated")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get config value by dot notation (e.g., 'search.keywords')"""
        keys = key.split('.')
        value = self.config
        
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k, default)
            else:
                return default
        
        return value
    
    # === Search Config ===
    
    def get_keywords(self) -> List[str]:
        """Get list of job search keywords"""
        return self.get('search.keywords', [])
    
    def get_location(self) -> str:
        """Get job search location"""
        return self.get('search.location', 'Remote')
    
    def get_max_results(self) -> int:
        """Get max results per search"""
        return self.get('search.max_results_per_search', 50)

    def get_max_pages(self) -> int:
        """Get max pages to paginate per search"""
        return int(self.get('search.max_pages', 1))

    def is_detail_salary_enabled(self) -> bool:
        """Check if detail salary fetch is enabled"""
        return bool(self.get('search.detail_salary_fetch', False))

    def get_detail_salary_timeout(self) -> int:
        """Get detail salary fetch timeout in seconds"""
        return int(self.get('search.detail_salary_timeout', 5))

    def get_detail_salary_retries(self) -> int:
        """Get detail salary fetch retries"""
        return int(self.get('search.detail_salary_retries', 1))

    def get_detail_salary_max_per_query(self) -> int:
        """Get max detail salary fetches per query"""
        return int(self.get('search.detail_salary_max_per_query', 10))

    def get_detail_salary_delay_min(self) -> float:
        """Get minimum delay between detail salary fetches in seconds"""
        return float(self.get('search.detail_salary_delay_min', 1.0))

    def get_detail_salary_delay_max(self) -> float:
        """Get maximum delay between detail salary fetches in seconds"""
        return float(self.get('search.detail_salary_delay_max', 2.0))

    def is_detail_description_enabled(self) -> bool:
        """Check if detail description fetch is enabled"""
        return bool(self.get('search.detail_description_fetch', False))

    def get_detail_description_timeout(self) -> int:
        """Get detail description fetch timeout in seconds"""
        return int(self.get('search.detail_description_timeout', 8))

    def get_detail_description_retries(self) -> int:
        """Get detail description fetch retries"""
        return int(self.get('search.detail_description_retries', 1))

    def get_detail_description_max_per_query(self) -> int:
        """Get max detail description fetches per query"""
        return int(self.get('search.detail_description_max_per_query', 10))

    def get_detail_description_delay_min(self) -> float:
        """Get minimum delay between detail description fetches in seconds"""
        return float(self.get('search.detail_description_delay_min', 1.0))

    def get_detail_description_delay_max(self) -> float:
        """Get maximum delay between detail description fetches in seconds"""
        return float(self.get('search.detail_description_delay_max', 2.0))

    def is_detail_company_enabled(self) -> bool:
        """Check if detail company fetch is enabled"""
        return bool(self.get('search.detail_company_fetch', True))
    
    def get_job_boards(self) -> List[str]:
        """Get list of job boards to search"""
        return self.get('search.job_boards', ['target-site'])
    
    # === Output Config ===
    
    def get_output_path(self, file_type: str = 'json') -> Path:
        """Get output file path with timestamp if enabled"""
        use_timestamp = self.get('output.use_timestamp', True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S') if use_timestamp else ''
        
        template = self.get(f'output.{file_type}_file', f'output/jobs.{file_type}')
        filename = template.replace('{timestamp}', timestamp)
        
        return Path(filename)
    
    # === Browser Config ===

    def is_headless(self) -> bool:
        """Check if browser should run in headless mode"""
        return self.get('browser.headless', False)

    def get_min_delay(self) -> float:
        """Get minimum delay between actions"""
        return float(self.get('browser.min_delay', 0.5))

    def get_max_delay(self) -> float:
        """Get maximum delay between actions"""
        return float(self.get('browser.max_delay', 2.0))

    def get_page_timeout(self) -> int:
        """Get page load timeout in milliseconds"""
        return self.get('browser.page_timeout', 30) * 1000

    def get_navigation_timeout(self) -> int:
        """Get navigation timeout in milliseconds"""
        return self.get('browser.navigation_timeout', 45) * 1000

    def get_launch_timeout(self) -> int:
        """Get browser launch timeout in milliseconds"""
        return self.get('browser.launch_timeout', 60) * 1000

    def get_max_retries(self) -> int:
        """Get max retries for navigation/extraction"""
        return int(self.get('browser.max_retries', 2))

    def get_browser_channel(self) -> str:
        """Get Playwright browser channel override"""
        return self.get('browser.channel', '')

    def get_browser_executable_path(self) -> str:
        """Get browser executable path override"""
        return self.get('browser.executable_path', '')

    def use_stealth(self) -> bool:
        """Check if Playwright stealth should be enabled"""
        return self.get('browser.use_stealth', False)

    # === Captcha Config ===

    def is_captcha_auto_solve_enabled(self) -> bool:
        """Check if captcha auto-solving should be attempted (disabled by default)."""
        enabled = self.get("captcha.enabled", None)
        if enabled is None:
            enabled = self.get("captcha.auto_solve", False)
        return bool(enabled)

    def get_captcha_provider(self) -> str:
        """Get captcha provider name (default env CAPTCHA_PROVIDER or '2captcha')."""
        provider = (self.get("captcha.provider", "") or "").strip()
        if provider:
            return provider
        env_provider = (os.getenv("CAPTCHA_PROVIDER") or "").strip()
        return env_provider or "2captcha"

    def get_captcha_api_key_env(self) -> str:
        """Get env var name that contains the captcha API key."""
        return (self.get("captcha.api_key_env", "") or "CAPTCHA_API_KEY").strip() or "CAPTCHA_API_KEY"

    def get_captcha_api_key(self) -> str:
        """Read captcha API key from env using captcha.api_key_env (never stored in config)."""
        env_name = self.get_captcha_api_key_env()
        return (os.getenv(env_name) or "").strip()

    def get_captcha_on_detect(self) -> str:
        """Get captcha policy action: abort | skip | pause."""
        value = (self.get("captcha.on_detect", "") or "").strip().lower()
        if not value:
            return "skip"
        if value not in ("abort", "skip", "pause"):
            logger.warning("Invalid captcha.on_detect value %r; defaulting to 'skip'", value)
            return "skip"
        return value

    def get_captcha_solve_timeout_seconds(self) -> int:
        """Get captcha solve timeout in seconds."""
        timeout = self.get("captcha.solve_timeout_seconds", None)
        if timeout is None:
            timeout = self.get("captcha.timeout", 180)
        return int(timeout)

    def get_captcha_max_solve_attempts(self) -> int:
        """Get max auto-solve attempts per captcha event."""
        attempts = self.get("captcha.max_solve_attempts", None)
        if attempts is None:
            attempts = self.get("captcha.max_retries", 1)
        return max(int(attempts), 1)

    def get_captcha_poll_interval_seconds(self) -> float:
        """Get captcha provider polling interval in seconds."""
        value = self.get("captcha.poll_interval_seconds", 5)
        return max(float(value), 1.0)

    # === Proxy Config ===

    def is_proxy_enabled(self) -> bool:
        """Check if Playwright proxy should be enabled (disabled by default)."""
        return bool(self.get("browser.proxy.enabled", False))

    def get_proxy_provider(self) -> str:
        provider = (self.get("browser.proxy.provider", "") or os.getenv("PROXY_PROVIDER") or "").strip().lower()
        return provider or "generic"

    def get_proxy_pool_size(self) -> int:
        value = self.get("browser.proxy.pool_size", 1)
        try:
            return max(int(value), 1)
        except Exception:
            return 1

    def is_proxy_sticky_session_enabled(self) -> bool:
        return bool(self.get("browser.proxy.sticky_session", True))

    def get_proxy_session_scope(self) -> str:
        scope = (self.get("browser.proxy.session_scope", "run") or "run").strip().lower()
        return scope if scope in ("run", "query") else "run"

    def get_proxy_session_ttl_seconds(self) -> int:
        value = self.get("browser.proxy.session_ttl_seconds", 0)
        try:
            return max(int(value), 0)
        except Exception:
            return 0

    def should_rotate_proxy_on_captcha(self) -> bool:
        return bool(self.get("browser.proxy.rotate_on_captcha", False))

    def should_rotate_proxy_on_failure(self) -> bool:
        return bool(self.get("browser.proxy.rotate_on_failure", False))

    def get_proxy_username_template(self) -> Optional[str]:
        template = (self.get("browser.proxy.username_template", "") or "").strip()
        return template or None

    def _get_proxy_server_raw(self) -> str:
        server = (self.get("browser.proxy.server", "") or "").strip()
        if server:
            return server

        host = (
            (self.get("browser.proxy.host", "") or "").strip()
            or (os.getenv("IPROYAL_HOST") or "").strip()
            or (os.getenv("IPROYAL_PROXY_HOST") or "").strip()
            or (os.getenv("PROXY_HOST") or "").strip()
        )
        port = str(
            (self.get("browser.proxy.port", "") or "").strip()
            or (os.getenv("IPROYAL_PORT") or "").strip()
            or (os.getenv("IPROYAL_PROXY_PORT") or "").strip()
            or (os.getenv("PROXY_PORT") or "").strip()
        ).strip()
        if host and port:
            return f"{host}:{port}"
        return ""

    def get_playwright_proxy(self) -> Optional[Dict[str, str]]:
        """
        Return a Playwright-ready proxy dict or None.

        Values may fall back to env vars (PROXY_HOST/PORT/USER/PASS), but the
        enabled flag must come from config (browser.proxy.enabled).
        """
        if not self.is_proxy_enabled():
            return None

        server_raw = self._get_proxy_server_raw()
        if not server_raw:
            raise ValueError(
                "Proxy is enabled but no server is configured. "
                "Set browser.proxy.server or browser.proxy.host+browser.proxy.port "
                "(or env PROXY_HOST+PROXY_PORT)."
            )

        server = server_raw if "://" in server_raw else f"http://{server_raw}"
        proxy: Dict[str, str] = {"server": server}

        username = (
            (self.get("browser.proxy.username", "") or "").strip()
            or (os.getenv("IPROYAL_USER") or "").strip()
            or (os.getenv("IPROYAL_USERNAME") or "").strip()
            or (os.getenv("PROXY_USER") or "").strip()
        )
        password = (
            (self.get("browser.proxy.password", "") or "").strip()
            or (os.getenv("IPROYAL_PASS") or "").strip()
            or (os.getenv("IPROYAL_PASSWORD") or "").strip()
            or (os.getenv("PROXY_PASS") or "").strip()
        )
        if username:
            proxy["username"] = username
        if password:
            proxy["password"] = password

        return proxy

    # Alias for backward compatibility
    get_proxy_config = get_playwright_proxy

    def get_proxy_manager_settings(self) -> Dict[str, Any]:
        """
        Return settings for shared.proxy_manager.ProxyManager.

        Sticky session behavior is provider-specific and handled by ProxyManager.
        """
        enabled = self.is_proxy_enabled()
        base_username = (
            (self.get("browser.proxy.username", "") or "").strip()
            or (os.getenv("IPROYAL_USER") or "").strip()
            or (os.getenv("IPROYAL_USERNAME") or "").strip()
            or (os.getenv("PROXY_USER") or "").strip()
        )
        base_password = (
            (self.get("browser.proxy.password", "") or "").strip()
            or (os.getenv("IPROYAL_PASS") or "").strip()
            or (os.getenv("IPROYAL_PASSWORD") or "").strip()
            or (os.getenv("PROXY_PASS") or "").strip()
        )
        server = ""
        if enabled:
            proxy = self.get_playwright_proxy()
            server = proxy["server"]

        return {
            "enabled": bool(enabled),
            "provider": self.get_proxy_provider(),
            "server": server,
            "username": base_username,
            "password": base_password,
            "username_template": self.get_proxy_username_template(),
            "sticky_session": self.is_proxy_sticky_session_enabled(),
            "session_scope": self.get_proxy_session_scope(),
            "pool_size": self.get_proxy_pool_size(),
            "session_ttl_seconds": self.get_proxy_session_ttl_seconds(),
            "rotate_on_captcha": self.should_rotate_proxy_on_captcha(),
            "rotate_on_failure": self.should_rotate_proxy_on_failure(),
        }
    
    # === AI Config ===
    
    def is_ai_enabled(self) -> bool:
        """Check if AI filtering is enabled"""
        return self.get('ai_filter.enabled', False)
    
    def get_ai_model(self) -> str:
        """Get AI model name"""
        return self.get('ai_filter.model', 'deepseek-coder-v2:latest')
    
    def get_ai_prompt(self) -> str:
        """Get AI scoring prompt template"""
        return self.get('ai_filter.scoring_prompt', '')

    def get_ai_max_retries(self) -> int:
        """Get max retries for AI scoring calls"""
        return int(self.get('ai_filter.max_retries', 2))

    def get_ai_max_reasoning_chars(self) -> int:
        """Get max characters to keep for AI reasoning"""
        return int(self.get('ai_filter.max_reasoning_chars', 400))

    def get_ai_debug(self) -> bool:
        """Check if AI debug logging is enabled"""
        return bool(self.get('ai_filter.debug', False))

    def is_ai_reasoning_enabled(self) -> bool:
        """Check if AI reasoning should be included"""
        return bool(self.get('ai_filter.include_reasoning', True))

    # === Dedupe Config ===

    def is_dedupe_enabled(self) -> bool:
        """Check if cross-run dedupe is enabled"""
        return self.get('dedupe.enabled', False)

    def get_dedupe_path(self) -> Path:
        """Get dedupe hash log path"""
        path = self.get('dedupe.hash_file', '')
        return Path(path) if path else None
    
    # === Vault Sync Config ===

    def is_vault_sync_enabled(self) -> bool:
        """Check if Obsidian vault sync is enabled"""
        return self.get('output.vault_sync.enabled', False)

    def get_vault_path(self) -> Path:
        """Get Obsidian vault path for syncing output"""
        path = self.get('output.vault_sync.vault_path', '')
        return Path(path) if path else None

    # === Notification Config ===

    def is_notifications_enabled(self) -> bool:
        """Check if desktop notifications are enabled (default: True on macOS, False elsewhere)"""
        import sys
        explicit = self.get('notifications.enabled', None)
        if explicit is not None:
            return bool(explicit)
        return sys.platform == "darwin"

    # === Logging Config ===

    def get_log_level(self) -> str:
        """Get logging level"""
        return self.get('logging.level', 'INFO')
    
    def get_log_file(self) -> Path:
        """Get log file path with timestamp"""
        template = self.get('logging.log_file', 'logs/job_bot.log')
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = template.replace('{timestamp}', timestamp)
        return Path(filename)
    
    def __repr__(self) -> str:
        keywords = self.get_keywords()
        location = self.get_location()
        return f"<Config: {len(keywords)} keywords, location={location}>"


# Convenience function
def load_config(config_path: str = "config/settings.yaml") -> ConfigLoader:
    """Load configuration from file"""
    return ConfigLoader(config_path)
