"""
Capsolver integration helpers (Turnstile-focused).

This module is intentionally lightweight so board collectors can use CapSolver
directly without pulling in higher-level abstractions.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


class CapsolverError(RuntimeError):
    pass


def extract_turnstile_sitekey(page: Any) -> Optional[str]:
    """Best-effort extraction of Cloudflare Turnstile sitekey from a Playwright page."""
    if page is None:
        return None

    try:
        elem = page.query_selector("[data-sitekey]")
        if elem:
            sitekey = (elem.get_attribute("data-sitekey") or "").strip()
            if sitekey:
                return sitekey
    except Exception:
        pass

    try:
        elem = page.query_selector(".cf-turnstile")
        if elem:
            sitekey = (elem.get_attribute("data-sitekey") or "").strip()
            if sitekey:
                return sitekey
    except Exception:
        pass

    try:
        sitekey = page.evaluate(
            """
            () => {
              const el = document.querySelector('.cf-turnstile,[data-sitekey]');
              if (el) return el.getAttribute('data-sitekey');
              const iframes = Array.from(document.querySelectorAll("iframe[src*='challenges.cloudflare.com']"));
              for (const f of iframes) {
                const src = f.getAttribute('src') || '';
                const m = src.match(/\\/(0x[a-fA-F0-9]+)/);
                if (m) return m[1];
              }
              return null;
            }
            """
        )
        sitekey = (sitekey or "").strip()
        return sitekey or None
    except Exception:
        return None


def _capsolver_post_json(path: str, payload: dict, *, timeout_seconds: int = 30) -> dict:
    url = f"https://api.capsolver.com{path}"
    try:
        resp = requests.post(url, json=payload, timeout=timeout_seconds)
    except requests.RequestException as exc:
        raise CapsolverError(f"capsolver request error: {exc}") from exc

    text = resp.text or ""
    if not resp.ok:
        raise CapsolverError(f"capsolver HTTP {resp.status_code}: {text[:200]}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise CapsolverError(f"capsolver invalid JSON: {text[:200]}") from exc

    if not isinstance(data, dict):
        raise CapsolverError("capsolver returned unexpected response shape")
    return data


def solve_turnstile_capsolver(
    page_url: str,
    sitekey: str,
    *,
    api_key: Optional[str] = None,
    timeout_seconds: int = 120,
    poll_interval_seconds: int = 3,
) -> str:
    """
    Solve a Cloudflare Turnstile challenge via CapSolver and return the token.

    Raises CapsolverError on failures.
    """
    api_key = (api_key or os.getenv("CAPSOLVER_API_KEY") or "").strip()
    if not api_key:
        raise CapsolverError("missing CAPSOLVER_API_KEY")

    page_url = (page_url or "").strip()
    sitekey = (sitekey or "").strip()
    if not page_url:
        raise CapsolverError("missing page_url")
    if not sitekey:
        raise CapsolverError("missing sitekey")

    task_payload = {
        "clientKey": api_key,
        "task": {
            "type": "AntiTurnstileTaskProxyLess",
            "websiteURL": page_url,
            "websiteKey": sitekey,
        },
    }
    created = _capsolver_post_json("/createTask", task_payload)
    if int(created.get("errorId", 0) or 0) != 0:
        raise CapsolverError(f"capsolver createTask error: {created.get('errorDescription') or 'unknown'}")

    task_id = created.get("taskId")
    if not task_id:
        raise CapsolverError("capsolver createTask returned no taskId")

    deadline = time.monotonic() + max(int(timeout_seconds), 1)
    poll_interval = max(float(poll_interval_seconds), 1.0)

    while time.monotonic() < deadline:
        result = _capsolver_post_json(
            "/getTaskResult",
            {"clientKey": api_key, "taskId": task_id},
        )
        if int(result.get("errorId", 0) or 0) != 0:
            raise CapsolverError(
                f"capsolver getTaskResult error: {result.get('errorDescription') or 'unknown'}"
            )

        status = (result.get("status") or "").strip().lower()
        if status == "ready":
            solution = result.get("solution", {}) or {}
            token = (solution.get("token") or solution.get("gRecaptchaResponse") or "").strip()
            if not token:
                raise CapsolverError("capsolver returned empty token")
            return token
        if status == "processing":
            time.sleep(poll_interval)
            continue
        raise CapsolverError(f"capsolver unexpected status: {status or 'empty'}")

    raise CapsolverError("capsolver timed out waiting for solution")


def _inject_turnstile_token(page: Any, token: str) -> bool:
    try:
        return bool(
            page.evaluate(
                """
                (token) => {
                  const fire = (el) => {
                    try { el.dispatchEvent(new Event('input', { bubbles: true })); } catch (e) {}
                    try { el.dispatchEvent(new Event('change', { bubbles: true })); } catch (e) {}
                  };

                  let injected = false;

                  const inputs = [
                    'input[name=\"cf-turnstile-response\"]',
                    'textarea[name=\"cf-turnstile-response\"]',
                    'input[name=\"g-recaptcha-response\"]',
                    'textarea[name=\"g-recaptcha-response\"]',
                  ];
                  for (const sel of inputs) {
                    const el = document.querySelector(sel);
                    if (el) {
                      el.value = token;
                      fire(el);
                      injected = true;
                    }
                  }

                  const widgets = document.querySelectorAll('.cf-turnstile,[data-sitekey]');
                  for (const w of widgets) {
                    const cb = w.getAttribute('data-callback');
                    if (cb && typeof window[cb] === 'function') {
                      try { window[cb](token); injected = true; } catch (e) {}
                    }
                  }

                  if (injected) {
                    const form = document.querySelector('form');
                    if (form && typeof form.submit === 'function') {
                      try { form.submit(); } catch (e) {}
                    }
                  }

                  return injected;
                }
                """,
                token,
            )
        )
    except Exception:
        return False


def solve_turnstile_on_page_capsolver(
    page: Any,
    *,
    api_key: Optional[str] = None,
    timeout_seconds: int = 120,
    poll_interval_seconds: int = 3,
    estimated_cost_usd_per_solve: float = 0.0025,
) -> Tuple[bool, str, bool]:
    """
    Solve & inject a Turnstile token for the current page.

    Returns (ok, reason, attempted) where attempted=True means a CapSolver task was created.
    """
    if page is None:
        return False, "no_page", False

    page_url = (getattr(page, "url", "") or "").strip()
    sitekey = extract_turnstile_sitekey(page)
    if not sitekey:
        return False, "no_sitekey_found", False

    api_key = (api_key or os.getenv("CAPSOLVER_API_KEY") or "").strip()
    if not api_key:
        return False, "capsolver_not_configured", False

    started = time.monotonic()
    logger.info("CapSolver: solving Turnstile (sitekey=%s..., url=%s)", sitekey[:16], page_url)

    token: Optional[str] = None
    try:
        token = solve_turnstile_capsolver(
            page_url,
            sitekey,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
    except Exception as exc:
        logger.warning("CapSolver: solve failed: %s", exc)
        return False, f"capsolver_error:{exc}", True

    injected = _inject_turnstile_token(page, token)
    elapsed = time.monotonic() - started
    if not injected:
        logger.warning("CapSolver: token solved but injection failed (%.1fs)", elapsed)
        return False, "injection_failed", True

    logger.info(
        "CapSolver: token injected (%.1fs, est_cost=$%.4f)",
        elapsed,
        float(estimated_cost_usd_per_solve),
    )
    return True, "solved", True

