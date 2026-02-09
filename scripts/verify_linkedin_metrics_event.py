#!/usr/bin/env python3
"""
Regression guard for LinkedIn collector metrics-event naming.

Historical bug: JobCollector._metrics_event(kind, **data) collided with callers that
also passed `kind=...` in kwargs, causing:
  JobCollector._metrics_event() got multiple values for argument 'kind'

This script statically inspects the LinkedIn collector source to ensure:
- `_metrics_event` does not use `kind` as its event-name parameter
- detail-queue events use `detail_kind=` (not `kind=`) for payload disambiguation
"""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = REPO_ROOT / "boards" / "linkedin" / "src" / "collector.py"


def _kw_names(call: ast.Call) -> set[str]:
    names: set[str] = set()
    for kw in call.keywords or []:
        if kw.arg:
            names.add(kw.arg)
    return names


def main() -> int:
    if not COLLECTOR.exists():
        raise SystemExit(f"Missing expected file: {COLLECTOR}")

    tree = ast.parse(COLLECTOR.read_text(encoding="utf-8"))

    event_param_ok = False
    detail_events_ok = {"detail_queue_give_up": False, "detail_queue_retry_scheduled": False}

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_metrics_event":
            args = node.args.args
            if len(args) >= 2:
                # args[0] is `self`
                if args[1].arg != "kind":
                    event_param_ok = True

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_metrics_event":
            if not node.args:
                continue
            first = node.args[0]
            if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                continue
            name = first.value
            if name not in detail_events_ok:
                continue
            kws = _kw_names(node)
            if "kind" in kws:
                raise SystemExit(
                    f"{COLLECTOR}: `{name}` must not pass `kind=` to _metrics_event (use `detail_kind=`)."
                )
            if "detail_kind" not in kws:
                raise SystemExit(
                    f"{COLLECTOR}: `{name}` must include `detail_kind=` in _metrics_event payload."
                )
            detail_events_ok[name] = True

    if not event_param_ok:
        raise SystemExit(f"{COLLECTOR}: `_metrics_event` event-name parameter is still named `kind`.")

    missing = [k for k, ok in detail_events_ok.items() if not ok]
    if missing:
        raise SystemExit(f"{COLLECTOR}: missing expected _metrics_event calls for: {', '.join(missing)}")

    print("OK: LinkedIn _metrics_event collision guard passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

