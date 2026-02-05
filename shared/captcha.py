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
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

TURNSTILE_RENDER_HOOK_SCRIPT = r"""
(() => {
  const MAX = 20;

  const store = () => {
    if (!window.__jobbot_turnstile_renders) window.__jobbot_turnstile_renders = [];
    return window.__jobbot_turnstile_renders;
  };

  const push = (entry) => {
    try {
      const arr = store();
      arr.push(entry);
      while (arr.length > MAX) arr.shift();
    } catch (e) {}
  };

  const safeContainer = (container) => {
    try {
      if (!container) return null;
      if (typeof container === 'string') return container.slice(0, 200);
      if (container instanceof Element) {
        const id = container.getAttribute && container.getAttribute('id');
        if (id) return '#' + String(id).slice(0, 120);
        const name = container.tagName ? container.tagName.toLowerCase() : 'element';
        return name;
      }
      return null;
    } catch (e) {
      return null;
    }
  };

  const hook = () => {
    try {
      if (!window.turnstile) return;
      if (window.turnstile.__jobbot_hooked) return;
      const orig = window.turnstile.render;
      if (typeof orig !== 'function') return;

      window.turnstile.__jobbot_hooked = true;
      if (!window.__jobbot_turnstile_callbacks) window.__jobbot_turnstile_callbacks = {};

      window.turnstile.render = function(container, params) {
        let widgetId = null;
        try {
          widgetId = orig.apply(this, arguments);
        } catch (e) {
          // If the original render throws, still capture params for debugging.
        }

        try {
          const p = params || {};
          const sitekey = p.sitekey || p['sitekey'] || null;
          const action = p.action || p['action'] || null;
          const cData = p.cData || p['cData'] || p.cdata || p['cdata'] || null;
          const chlPageData = p.chlPageData || p['chlPageData'] || null;

          const cb = p.callback || p['callback'];
          const hasCallback = !!cb;
          if (hasCallback && typeof cb === 'function' && widgetId != null) {
            try { window.__jobbot_turnstile_callbacks[String(widgetId)] = cb; } catch (e) {}
          }

          push({
            ts: Date.now(),
            href: String(location && location.href ? location.href : ''),
            widgetId: widgetId != null ? String(widgetId) : null,
            container: safeContainer(container),
            sitekey: sitekey ? String(sitekey) : null,
            action: action ? String(action) : null,
            cData: cData ? String(cData) : null,
            chlPageData: chlPageData ? String(chlPageData) : null,
            hasCallback,
          });
        } catch (e) {}

        return widgetId;
      };
    } catch (e) {}
  };

  hook();
  const t = setInterval(hook, 250);
  setTimeout(() => { try { clearInterval(t); } catch (e) {} }, 15000);
})();
"""


class CapsolverError(RuntimeError):
    pass


def install_turnstile_render_hook(*, context: Any = None, page: Any = None) -> None:
    """
    Install a Turnstile render-hook so Turnstile params are captured at render-time.

    This is required on many Cloudflare interstitials where the sitekey/action/cData are
    only present in the `turnstile.render(...)` arguments, not in the DOM.
    """
    try:
        if context is not None:
            context.add_init_script(TURNSTILE_RENDER_HOOK_SCRIPT)
    except Exception:
        pass

    try:
        if page is not None:
            page.add_init_script(TURNSTILE_RENDER_HOOK_SCRIPT)
    except Exception:
        pass

    try:
        if page is not None:
            page.evaluate(TURNSTILE_RENDER_HOOK_SCRIPT)
    except Exception:
        pass


def extract_turnstile_params(page: Any) -> Optional[dict]:
    """Extract Turnstile params from our render-hook, falling back to DOM heuristics."""
    if page is None:
        return None

    try:
        entry = page.evaluate(
            """
            () => {
              const arr = window.__jobbot_turnstile_renders;
              if (!Array.isArray(arr) || !arr.length) return null;
              const last = arr[arr.length - 1] || null;
              if (!last) return null;
              return {
                sitekey: last.sitekey || null,
                action: last.action || null,
                cData: last.cData || null,
                chlPageData: last.chlPageData || null,
                widgetId: last.widgetId || null,
                hasCallback: !!last.hasCallback,
              };
            }
            """
        )
        if isinstance(entry, dict):
            sitekey = (entry.get("sitekey") or "").strip()
            if sitekey:
                action = (entry.get("action") or "").strip() or None
                cdata = (entry.get("cData") or "").strip() or None
                widget_id = (entry.get("widgetId") or "").strip() or None
                return {"sitekey": sitekey, "action": action, "cdata": cdata, "widget_id": widget_id}
    except Exception:
        pass

    sitekey = extract_turnstile_sitekey(page)
    if sitekey:
        return {"sitekey": sitekey, "action": None, "cdata": None, "widget_id": None}
    return None


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


def _playwright_proxy_to_capsolver(proxy: Any) -> Optional[str]:
    """
    Convert a Playwright proxy dict into a CapSolver proxy string.

    Playwright typically uses: {"server": "http://host:port", "username": "...", "password": "..."}.
    CapSolver accepts URL-style proxies for proxy-based tasks.
    """
    if not proxy or not isinstance(proxy, dict):
        return None

    server = (proxy.get("server") or "").strip()
    if not server:
        return None

    try:
        parsed = urlparse(server if "://" in server else f"http://{server}")
        scheme = (parsed.scheme or "http").lower()
        host = parsed.hostname
        port = parsed.port
        if not host or not port:
            return None
    except Exception:
        return None

    username = (proxy.get("username") or "").strip()
    password = (proxy.get("password") or "").strip()
    if username and password:
        return f"{scheme}://{username}:{password}@{host}:{int(port)}"
    return f"{scheme}://{host}:{int(port)}"


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
    action: Optional[str] = None,
    cdata: Optional[str] = None,
    proxy: Any = None,
    user_agent: Optional[str] = None,
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

    def _build_task(task_type: str, *, with_proxy: bool) -> dict:
        task: dict = {
            "type": task_type,
            "websiteURL": page_url,
            "websiteKey": sitekey,
        }
        metadata = {}
        action_value = (action or "").strip()
        cdata_value = (cdata or "").strip()
        if action_value:
            metadata["action"] = action_value
        if cdata_value:
            metadata["cdata"] = cdata_value
        if metadata:
            task["metadata"] = metadata

        if with_proxy:
            proxy_str = _playwright_proxy_to_capsolver(proxy) if isinstance(proxy, dict) else str(proxy)
            proxy_str = (proxy_str or "").strip()
            if proxy_str:
                task["proxy"] = proxy_str
            ua_value = (user_agent or "").strip()
            if ua_value:
                task["userAgent"] = ua_value
        return task

    def _create_task(task: dict) -> str:
        created = _capsolver_post_json("/createTask", {"clientKey": api_key, "task": task})
        if int(created.get("errorId", 0) or 0) != 0:
            raise CapsolverError(f"capsolver createTask error: {created.get('errorDescription') or 'unknown'}")
        task_id = created.get("taskId")
        if not task_id:
            raise CapsolverError("capsolver createTask returned no taskId")
        return str(task_id)

    use_proxy = bool(proxy)
    task_id: Optional[str] = None
    if use_proxy:
        try:
            task_id = _create_task(_build_task("AntiTurnstileTask", with_proxy=True))
        except CapsolverError as exc:
            logger.warning("CapSolver: proxy Turnstile createTask failed (%s); falling back to proxyless", exc)

    if not task_id:
        task_id = _create_task(_build_task("AntiTurnstileTaskProxyLess", with_proxy=False))

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


def solve_cloudflare_challenge_capsolver(
    page_url: str,
    *,
    proxy: Any,
    user_agent: Optional[str] = None,
    html: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout_seconds: int = 180,
    poll_interval_seconds: int = 3,
) -> dict:
    """
    Solve a Cloudflare "Just a moment..." challenge via CapSolver AntiCloudflareTask.

    Returns the solution dict (cookies/token/userAgent/etc) on success.
    """
    api_key = (api_key or os.getenv("CAPSOLVER_API_KEY") or "").strip()
    if not api_key:
        raise CapsolverError("missing CAPSOLVER_API_KEY")

    page_url = (page_url or "").strip()
    if not page_url:
        raise CapsolverError("missing page_url")

    proxy_str = _playwright_proxy_to_capsolver(proxy) if isinstance(proxy, dict) else str(proxy)
    proxy_str = (proxy_str or "").strip()
    if not proxy_str:
        raise CapsolverError("missing proxy (AntiCloudflareTask requires a static/sticky proxy)")

    task: dict = {
        "type": "AntiCloudflareTask",
        "websiteURL": page_url,
        "proxy": proxy_str,
    }
    ua_value = (user_agent or "").strip()
    if ua_value:
        task["userAgent"] = ua_value
    html_value = (html or "").strip()
    if html_value:
        task["html"] = html_value

    created = _capsolver_post_json("/createTask", {"clientKey": api_key, "task": task})
    if int(created.get("errorId", 0) or 0) != 0:
        raise CapsolverError(f"capsolver createTask error: {created.get('errorDescription') or 'unknown'}")

    task_id = created.get("taskId")
    if not task_id:
        raise CapsolverError("capsolver createTask returned no taskId")

    deadline = time.monotonic() + max(int(timeout_seconds), 1)
    poll_interval = max(float(poll_interval_seconds), 1.0)

    while time.monotonic() < deadline:
        result = _capsolver_post_json("/getTaskResult", {"clientKey": api_key, "taskId": task_id})
        if int(result.get("errorId", 0) or 0) != 0:
            raise CapsolverError(
                f"capsolver getTaskResult error: {result.get('errorDescription') or 'unknown'}"
            )

        status = (result.get("status") or "").strip().lower()
        if status == "ready":
            solution = result.get("solution", {}) or {}
            if not isinstance(solution, dict) or not solution:
                raise CapsolverError("capsolver returned empty Cloudflare solution")
            return solution
        if status == "processing":
            time.sleep(poll_interval)
            continue
        raise CapsolverError(f"capsolver unexpected status: {status or 'empty'}")

    raise CapsolverError("capsolver timed out waiting for Cloudflare solution")


def _inject_cloudflare_solution(page: Any, page_url: str, solution: dict) -> bool:
    """
    Inject Cloudflare clearance cookies (and optionally UA) into the current Playwright context.

    Returns True if injection was attempted successfully.
    """
    if page is None or not solution or not isinstance(solution, dict):
        return False

    context = None
    try:
        context = page.context
    except Exception:
        context = None
    if context is None:
        return False

    cookies_obj = solution.get("cookies") or {}
    cookies_to_set: list[dict] = []
    if isinstance(cookies_obj, dict):
        for name, value in cookies_obj.items():
            name_s = (str(name) if name is not None else "").strip()
            value_s = (str(value) if value is not None else "").strip()
            if name_s and value_s:
                cookies_to_set.append({"name": name_s, "value": value_s, "url": page_url})

    token = (solution.get("token") or "").strip()
    if token and not any(c.get("name") == "cf_clearance" for c in cookies_to_set):
        cookies_to_set.append({"name": "cf_clearance", "value": token, "url": page_url})

    try:
        if cookies_to_set:
            context.add_cookies(cookies_to_set)
    except Exception:
        return False

    ua_value = (solution.get("userAgent") or "").strip()
    if ua_value:
        try:
            context.set_extra_http_headers({"User-Agent": ua_value})
        except Exception:
            pass
        try:
            ua = ua_value.replace("\\", "\\\\").replace("'", "\\'")
            context.add_init_script("Object.defineProperty(navigator,'userAgent',{get:()=>'" + ua + "'});")
        except Exception:
            pass

    return True


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

                  try {
                    const arr = window.__jobbot_turnstile_renders;
                    const last = Array.isArray(arr) && arr.length ? arr[arr.length - 1] : null;
                    const widgetId = last && last.widgetId ? String(last.widgetId) : null;
                    const cbs = window.__jobbot_turnstile_callbacks;
                    if (widgetId && cbs && typeof cbs[widgetId] === 'function') {
                      try { cbs[widgetId](token); injected = true; } catch (e) {}
                    }
                  } catch (e) {}

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
    proxy: Any = None,
    user_agent: Optional[str] = None,
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
    params = extract_turnstile_params(page)
    if not params:
        for _ in range(10):
            time.sleep(0.5)
            params = extract_turnstile_params(page)
            if params:
                break
    if not user_agent:
        try:
            user_agent = (page.evaluate("() => navigator.userAgent") or "").strip() or None
        except Exception:
            user_agent = None

    if not params or not (params.get("sitekey") or "").strip():
        if proxy:
            try:
                title = (page.title() or "").lower()
            except Exception:
                title = ""
            url_lower = page_url.lower()
            if (
                "__cf_chl" in url_lower
                or "/cdn-cgi/" in url_lower
                or "challenges.cloudflare.com" in url_lower
                or "just a moment" in title
                or "security check" in title
                or "additional verification" in title
            ):
                logger.info("CapSolver: Cloudflare page detected without Turnstile params; trying AntiCloudflareTask")
                api_key_effective = (api_key or os.getenv("CAPSOLVER_API_KEY") or "").strip()
                if not api_key_effective:
                    return False, "capsolver_not_configured", False
                try:
                    solution = solve_cloudflare_challenge_capsolver(
                        page_url,
                        proxy=proxy,
                        user_agent=user_agent,
                        api_key=api_key_effective,
                        timeout_seconds=max(int(timeout_seconds), 120),
                        poll_interval_seconds=poll_interval_seconds,
                    )
                    injected_ok = _inject_cloudflare_solution(page, page_url, solution)
                    if injected_ok:
                        try:
                            page.reload(wait_until="domcontentloaded")
                        except Exception:
                            pass
                        logger.info("CapSolver: Cloudflare clearance injected")
                        return True, "cloudflare_injected", True
                    return False, "cloudflare_injection_failed", True
                except Exception as cf_exc:
                    logger.warning("CapSolver: AntiCloudflareTask failed: %s", cf_exc)
                    return False, f"cloudflare_error:{cf_exc}", True

        return False, "no_sitekey_found", False

    sitekey = (params.get("sitekey") or "").strip()
    action = (params.get("action") or "").strip() or None
    cdata = (params.get("cdata") or "").strip() or None

    api_key = (api_key or os.getenv("CAPSOLVER_API_KEY") or "").strip()
    if not api_key:
        return False, "capsolver_not_configured", False

    started = time.monotonic()
    logger.info(
        "CapSolver: solving Turnstile (sitekey=%s..., action=%s, cdata=%s, proxy=%s, url=%s)",
        sitekey[:16],
        "yes" if action else "no",
        "yes" if cdata else "no",
        "enabled" if proxy else "disabled",
        page_url,
    )

    token: Optional[str] = None
    try:
        token = solve_turnstile_capsolver(
            page_url,
            sitekey,
            action=action,
            cdata=cdata,
            proxy=proxy,
            user_agent=user_agent,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
    except Exception as exc:
        msg = str(exc)
        lower = msg.lower()
        if "challenge, not turnstile" in lower or "sitekey is challenge" in lower:
            if not proxy:
                logger.warning("CapSolver: challenge-mode sitekey detected but no proxy provided; cannot run AntiCloudflareTask")
                return False, "cloudflare_requires_proxy", True

            logger.info("CapSolver: challenge-mode Turnstile detected; switching to AntiCloudflareTask")
            try:
                solution = solve_cloudflare_challenge_capsolver(
                    page_url,
                    proxy=proxy,
                    user_agent=user_agent,
                    api_key=api_key,
                    timeout_seconds=max(int(timeout_seconds), 120),
                    poll_interval_seconds=poll_interval_seconds,
                )
                injected_ok = _inject_cloudflare_solution(page, page_url, solution)
                if injected_ok:
                    try:
                        page.reload(wait_until="domcontentloaded")
                    except Exception:
                        pass
                    try:
                        title = (page.title() or "").lower()
                        url = (getattr(page, "url", "") or "").lower()
                        if "just a moment" not in title and "__cf_chl" not in url and "/cdn-cgi/" not in url:
                            logger.info("CapSolver: Cloudflare clearance injected and challenge cleared")
                            return True, "cloudflare_solved", True
                    except Exception:
                        pass
                    logger.info("CapSolver: Cloudflare clearance injected; unable to confirm challenge cleared yet")
                    return True, "cloudflare_injected", True
                return False, "cloudflare_injection_failed", True
            except Exception as cf_exc:
                logger.warning("CapSolver: AntiCloudflareTask failed: %s", cf_exc)
                return False, f"cloudflare_error:{cf_exc}", True

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
