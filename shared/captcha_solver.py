import json
import time
import urllib.parse
import urllib.request
from typing import Optional


class CaptchaSolveError(RuntimeError):
    pass


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

