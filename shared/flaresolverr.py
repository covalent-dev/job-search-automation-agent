"""
FlareSolverr client for solving Cloudflare JS challenges.

This module is OPTIONAL: all callers must handle FlareSolverr being absent or
unavailable.

References:
- FlareSolverr API: POST /v1 with {"cmd":"request.get", ...}
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FlareSolverResult:
    success: bool
    cookies: List[Dict[str, Any]]
    user_agent: str
    error: Optional[str] = None


def flaresolverr_cookies_to_playwright(cookies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convert FlareSolverr cookies to Playwright context.add_cookies() format.

    FlareSolverr cookie fields typically include:
      - name, value, domain, path, expiry, httpOnly, secure, sameSite
    """
    converted: List[Dict[str, Any]] = []
    for cookie in cookies or []:
        if not isinstance(cookie, dict):
            continue
        name = cookie.get("name")
        value = cookie.get("value")
        domain = cookie.get("domain")
        if not name or value is None or not domain:
            continue
        converted.append(
            {
                "name": str(name),
                "value": str(value),
                "domain": str(domain),
                "path": str(cookie.get("path") or "/"),
                "expires": int(cookie.get("expiry") or -1),
                "httpOnly": bool(cookie.get("httpOnly") or False),
                "secure": bool(cookie.get("secure") or False),
                "sameSite": str(cookie.get("sameSite") or "Lax"),
            }
        )
    return converted


class FlareSolverr:
    def __init__(self, url: str = "http://localhost:8191", timeout: int = 60):
        self.url = (url or "http://localhost:8191").rstrip("/")
        self.timeout = int(timeout or 60)
        self._available: Optional[bool] = None

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available

        try:
            data = self._request_json("GET", "/health", payload=None, timeout_seconds=5)
            self._available = bool(data.get("status") == "ok")
        except Exception:
            self._available = False

        return self._available

    def solve(self, target_url: str, *, proxy_url: Optional[str] = None) -> FlareSolverResult:
        """
        Solve Cloudflare challenge for target_url.

        Args:
            target_url: URL to visit/solve
            proxy_url: Optional proxy URL passed to FlareSolverr, e.g.
              "http://user:pass@host:port"
        """
        if not target_url:
            return FlareSolverResult(False, [], "", "Missing target_url")

        if not self.is_available():
            return FlareSolverResult(False, [], "", "FlareSolverr not available")

        payload: Dict[str, Any] = {
            "cmd": "request.get",
            "url": target_url,
            "maxTimeout": int(self.timeout) * 1000,
        }
        if proxy_url:
            payload["proxy"] = {"url": proxy_url}

        try:
            data = self._request_json(
                "POST",
                "/v1",
                payload=payload,
                timeout_seconds=max(10, int(self.timeout) + 10),
            )
        except Exception as exc:
            logger.warning("FlareSolverr error: %s", exc)
            return FlareSolverResult(False, [], "", str(exc))

        if data.get("status") != "ok":
            message = data.get("message") or data.get("error") or "Unknown error"
            return FlareSolverResult(False, [], "", str(message))

        solution = data.get("solution") or {}
        cookies = solution.get("cookies") or []
        user_agent = solution.get("userAgent") or ""
        return FlareSolverResult(True, list(cookies) if isinstance(cookies, list) else [], str(user_agent))

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: Optional[Dict[str, Any]],
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        url = f"{self.url}{path}"
        data: Optional[bytes] = None
        headers: Dict[str, str] = {}

        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8") if hasattr(exc, "read") else ""
            raise RuntimeError(f"HTTP {exc.code} from FlareSolverr: {body[:200]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Failed to reach FlareSolverr at {url}: {exc}") from exc

        try:
            parsed = json.loads(body or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Non-JSON response from FlareSolverr at {url}: {body[:200]}") from exc

        if not isinstance(parsed, dict):
            raise RuntimeError(f"Unexpected response type from FlareSolverr at {url}: {type(parsed)}")

        return parsed

