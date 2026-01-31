"""
Proxy manager for Playwright with session affinity ("sticky sessions").

Primary goal: keep a stable proxy session (and therefore IP, for providers that
support it) for the duration of a scrape, while allowing explicit rotation hooks
on captcha / repeated failures.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _now() -> float:
    return time.time()


def _stable_bucket(key: str, buckets: int) -> int:
    if buckets <= 1:
        return 0
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % buckets


def _looks_like_session_tagged(username: str) -> bool:
    lower = (username or "").lower()
    return "-session-" in lower or "_session_" in lower or "-sessid-" in lower or "_sessid_" in lower


@dataclass
class _SessionState:
    session_id: str
    expires_at: Optional[float]
    rotations: int = 0

    def is_expired(self) -> bool:
        return self.expires_at is not None and _now() >= self.expires_at


@dataclass(frozen=True)
class ProxyManagerSettings:
    enabled: bool
    provider: str
    server: str
    username: str
    password: str
    username_template: Optional[str]
    sticky_session: bool
    session_scope: str
    pool_size: int
    session_ttl_seconds: int
    rotate_on_captcha: bool
    rotate_on_failure: bool


class ProxyManager:
    """
    Manages a proxy endpoint + session affinity.

    Notes:
    - Playwright proxy settings are fixed per browser launch / context. Rotating
      a proxy means the caller must restart the browser/context.
    - Sticky behavior depends on the provider. For IPRoyal, session affinity is
      typically achieved by embedding a session token into the username. This
      module supports either:
        - `username_template` containing `{session}`, or
        - auto-appending `-session-{session}` for provider == "iproyal".
    """

    def __init__(self, config_or_settings):
        """
        Initialize ProxyManager from either a config object or ProxyManagerSettings.

        Args:
            config_or_settings: Either a ConfigLoader instance or ProxyManagerSettings
        """
        if isinstance(config_or_settings, ProxyManagerSettings):
            self.settings = config_or_settings
        else:
            # Assume it's a config object - extract settings
            self.settings = self._settings_from_config(config_or_settings)

        self._sessions: dict[int, _SessionState] = {}
        self._consecutive_captchas: int = 0
        self._rotate_threshold: int = 2
        self._needs_rotation: bool = False
        self._total_rotations: int = 0

        # Extract rotation threshold from config if available
        if hasattr(config_or_settings, "get"):
            proxy_config = config_or_settings.get("proxy", {}) or {}
            self._rotate_threshold = int(proxy_config.get("rotate_on_captcha_consecutive", 2))
        elif hasattr(config_or_settings, "get_proxy_config"):
            proxy_config = config_or_settings.get_proxy_config() or {}
            self._rotate_threshold = int(proxy_config.get("rotate_on_captcha_consecutive", 2))

    @staticmethod
    def _settings_from_config(config) -> "ProxyManagerSettings":
        """Extract ProxyManagerSettings from a config object."""
        proxy_config = {}
        if hasattr(config, "get_proxy_config"):
            proxy_config = config.get_proxy_config() or {}
        elif hasattr(config, "get"):
            proxy_config = config.get("proxy", {}) or {}

        enabled = bool(proxy_config.get("enabled", False))
        provider = (proxy_config.get("provider") or "http").strip()
        server = (proxy_config.get("server") or "").strip()
        username = (proxy_config.get("username") or "").strip()
        password = (proxy_config.get("password") or "").strip()
        username_template = proxy_config.get("username_template")

        # Handle sticky session settings
        sticky = proxy_config.get("sticky", True)
        session_param = proxy_config.get("session_param", "session")
        session_ttl = int(proxy_config.get("session_ttl", 1800))
        pool_size = int(proxy_config.get("pool_size", 4))
        rotate_on_captcha = bool(proxy_config.get("rotate_on_captcha_consecutive", 0) > 0)
        rotate_on_failure = bool(proxy_config.get("rotate_on_failure", False))

        return ProxyManagerSettings(
            enabled=enabled,
            provider=provider,
            server=server,
            username=username,
            password=password,
            username_template=username_template,
            sticky_session=sticky,
            session_scope="run",
            pool_size=pool_size,
            session_ttl_seconds=session_ttl,
            rotate_on_captcha=rotate_on_captcha,
            rotate_on_failure=rotate_on_failure,
        )

    @classmethod
    def from_config(cls, config: Any) -> "ProxyManager":
        """
        Build a ProxyManager from ConfigLoader.

        Requires ConfigLoader.get_proxy_manager_settings().
        """
        settings_dict = config.get_proxy_manager_settings()
        settings = ProxyManagerSettings(**settings_dict)
        return cls(settings)

    @property
    def enabled(self) -> bool:
        """Property alias for is_enabled() for convenience."""
        return bool(self.settings.enabled)

    def is_enabled(self) -> bool:
        return bool(self.settings.enabled)

    def should_rotate_on_captcha(self) -> bool:
        return bool(self.settings.rotate_on_captcha)

    def should_rotate_on_failure(self) -> bool:
        return bool(self.settings.rotate_on_failure)

    def _get_or_create_session(self, affinity_key: str) -> Optional[str]:
        if not self.settings.enabled or not self.settings.sticky_session:
            return None

        scope = (self.settings.session_scope or "run").strip().lower()
        if scope not in ("run", "query"):
            scope = "run"

        effective_key = "run" if scope == "run" else (affinity_key or "query")
        bucket = _stable_bucket(effective_key, int(self.settings.pool_size or 1))
        state = self._sessions.get(bucket)

        if state is None or state.is_expired():
            session_id = uuid.uuid4().hex[:12]
            ttl = int(self.settings.session_ttl_seconds or 0)
            expires_at = (_now() + ttl) if ttl > 0 else None
            state = _SessionState(session_id=session_id, expires_at=expires_at, rotations=0)
            self._sessions[bucket] = state

        return state.session_id

    def rotate(self, affinity_key: str = "run", *, session_key: str = None, reason: str = "manual") -> None:
        """
        Rotate the session used for this affinity_key.

        Caller must restart Playwright browser/context after calling rotate().

        Args:
            affinity_key: The affinity key for the session (positional or keyword)
            session_key: Alias for affinity_key (keyword only, for compatibility)
            reason: Reason for rotation (for logging)
        """
        # Allow session_key as alias for affinity_key
        if session_key is not None:
            affinity_key = session_key
        if not self.is_enabled():
            return

        scope = (self.settings.session_scope or "run").strip().lower()
        effective_key = "run" if scope == "run" else (affinity_key or "query")
        bucket = _stable_bucket(effective_key, int(self.settings.pool_size or 1))
        session_id = uuid.uuid4().hex[:12]
        ttl = int(self.settings.session_ttl_seconds or 0)
        expires_at = (_now() + ttl) if ttl > 0 else None
        prev = self._sessions.get(bucket)
        rotations = (prev.rotations + 1) if prev else 1
        self._sessions[bucket] = _SessionState(session_id=session_id, expires_at=expires_at, rotations=rotations)
        logger.info(
            "Proxy session rotated (provider=%s, scope=%s, bucket=%s, reason=%s)",
            self.settings.provider,
            scope,
            bucket,
            reason,
        )

    def _build_username(self, affinity_key: str) -> str:
        base = (self.settings.username or "").strip()
        template = (self.settings.username_template or "").strip() or None
        session_id = self._get_or_create_session(affinity_key)
        provider = (self.settings.provider or "generic").strip().lower()

        # Allow users to put `{session}` in username itself.
        if "{session}" in base and not template:
            template = base
            base = ""

        if template and session_id:
            return template.replace("{session}", session_id)

        if provider == "iproyal" and session_id and base and not _looks_like_session_tagged(base):
            return f"{base}-session-{session_id}"

        return base

    def get_playwright_proxy(self, affinity_key: str = "run") -> Optional[Dict[str, str]]:
        """
        Return Playwright proxy dict or None.

        Example:
          {"server": "http://host:port", "username": "...", "password": "..."}
        """
        if not self.settings.enabled:
            return None

        proxy: Dict[str, str] = {"server": self.settings.server}

        username = self._build_username(affinity_key)
        password = (self.settings.password or "").strip()

        if username:
            proxy["username"] = username
        if password:
            proxy["password"] = password

        return proxy

    def get_proxy(self, affinity_key: str = "run") -> Optional[Dict[str, str]]:
        """
        Alias for get_playwright_proxy for convenience.

        Returns Playwright-compatible proxy dict or None.
        """
        return self.get_playwright_proxy(affinity_key)

    def record_captcha(self, affinity_key: str = "run", *, session_key: str = None, solved: bool = False) -> bool:
        """
        Record a captcha event and check if rotation is needed.

        Args:
            affinity_key: The affinity key for the session (positional or keyword)
            session_key: Alias for affinity_key (keyword only, for compatibility)
            solved: Whether the captcha was successfully solved

        Returns:
            True if proxy rotation is needed (caller should restart browser)
        """
        # Allow session_key as alias for affinity_key
        if session_key is not None:
            affinity_key = session_key

        if solved:
            # Reset consecutive counter on successful solve
            self._consecutive_captchas = 0
            self._needs_rotation = False
            return False

        self._consecutive_captchas += 1
        logger.info(
            "Captcha recorded (consecutive=%d, threshold=%d)",
            self._consecutive_captchas,
            self._rotate_threshold,
        )

        if self._consecutive_captchas >= self._rotate_threshold:
            logger.info("Consecutive captcha threshold reached - rotation needed")
            self._needs_rotation = True
            return True

        return False

    def needs_rotation(self) -> bool:
        """Check if proxy rotation is needed."""
        return self._needs_rotation

    def perform_rotation(self, affinity_key: str = "run") -> None:
        """
        Perform proxy rotation and reset state.

        Caller must restart browser/context after this.
        """
        if not self.is_enabled():
            return

        self.rotate(affinity_key, reason="consecutive_captchas")
        self._consecutive_captchas = 0
        self._needs_rotation = False
        self._total_rotations += 1
        logger.info("Proxy rotation performed (total_rotations=%d)", self._total_rotations)

    def get_stats(self) -> Dict[str, Any]:
        """Get proxy manager statistics."""
        return {
            "enabled": self.is_enabled(),
            "consecutive_captchas": self._consecutive_captchas,
            "rotate_threshold": self._rotate_threshold,
            "needs_rotation": self._needs_rotation,
            "total_rotations": self._total_rotations,
        }

