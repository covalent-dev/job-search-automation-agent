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

    def __init__(self, settings: ProxyManagerSettings):
        self.settings = settings
        self._sessions: dict[int, _SessionState] = {}

    @classmethod
    def from_config(cls, config: Any) -> "ProxyManager":
        """
        Build a ProxyManager from ConfigLoader.

        Requires ConfigLoader.get_proxy_manager_settings().
        """
        settings_dict = config.get_proxy_manager_settings()
        settings = ProxyManagerSettings(**settings_dict)
        return cls(settings)

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

    def rotate(self, affinity_key: str, *, reason: str) -> None:
        """
        Rotate the session used for this affinity_key.

        Caller must restart Playwright browser/context after calling rotate().
        """
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

