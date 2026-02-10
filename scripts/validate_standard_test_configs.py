#!/usr/bin/env python3
"""Validate standardized test config levels across boards.

This enforces a stable config contract so reliability testing is repeatable and
not rebuilt ad-hoc per run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

STANDARD_BOARDS = ["remotejobs", "remoteafrica", "linkedin"]

REQUIRED_FILES = {
    "battery_smoke": "battery.smoke.noproxy.yaml",
    "battery_standard": "battery.standard.noproxy.yaml",
    "soak_noproxy_dedupe_off": "soak.production.noproxy.dedupe_off.yaml",
    "soak_noproxy_dedupe_on": "soak.production.noproxy.dedupe_on.yaml",
}

OPTIONAL_FILES = {
    "soak_proxy_dedupe_off": "soak.production.proxy.dedupe_off.yaml",
    "soak_proxy_dedupe_on": "soak.production.proxy.dedupe_on.yaml",
}


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def get_bool(data: dict[str, Any], *keys: str, default: bool = False) -> bool:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return bool(cur) if cur is not None else default


def validate_board(board: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    notes: list[str] = []
    config_dir = REPO_ROOT / "boards" / board / "config"

    if not config_dir.exists():
        errors.append(f"{board}: missing config directory: {config_dir}")
        return errors, notes

    resolved: dict[str, Path] = {}
    for key, file_name in REQUIRED_FILES.items():
        path = config_dir / file_name
        resolved[key] = path
        if not path.exists():
            errors.append(f"{board}: missing required file `{path.relative_to(REPO_ROOT)}`")

    for key, file_name in OPTIONAL_FILES.items():
        path = config_dir / file_name
        resolved[key] = path
        if not path.exists():
            notes.append(f"{board}: optional file not present `{path.relative_to(REPO_ROOT)}`")

    # Stop deep checks if core required files are missing.
    if errors:
        return errors, notes

    battery_smoke = load_yaml(resolved["battery_smoke"])
    battery_standard = load_yaml(resolved["battery_standard"])
    soak_off = load_yaml(resolved["soak_noproxy_dedupe_off"])
    soak_on = load_yaml(resolved["soak_noproxy_dedupe_on"])

    # Core invariants for standardized flow.
    for label, cfg in [("battery_smoke", battery_smoke), ("battery_standard", battery_standard), ("soak_dedupe_off", soak_off), ("soak_dedupe_on", soak_on)]:
        if get_bool(cfg, "output", "vault_sync", "enabled", default=False):
            errors.append(f"{board}:{label}: `output.vault_sync.enabled` must be false")

    if get_bool(soak_off, "dedupe", "enabled", default=True):
        errors.append(f"{board}: soak dedupe-off file has `dedupe.enabled=true`")
    if not get_bool(soak_on, "dedupe", "enabled", default=False):
        errors.append(f"{board}: soak dedupe-on file has `dedupe.enabled=false`")

    # Reliability collector focus in battery and soak should not depend on AI filter.
    for label, cfg in [("battery_smoke", battery_smoke), ("battery_standard", battery_standard), ("soak_dedupe_off", soak_off)]:
        if get_bool(cfg, "ai_filter", "enabled", default=False):
            errors.append(f"{board}:{label}: `ai_filter.enabled` must be false for standardized reliability flow")

    # Optional proxy pair checks when present.
    proxy_off_path = resolved["soak_proxy_dedupe_off"]
    proxy_on_path = resolved["soak_proxy_dedupe_on"]
    if proxy_off_path.exists() and proxy_on_path.exists():
        proxy_off = load_yaml(proxy_off_path)
        proxy_on = load_yaml(proxy_on_path)

        if not get_bool(proxy_off, "proxy", "enabled", default=False):
            errors.append(f"{board}: proxy dedupe-off config must have `proxy.enabled=true`")
        if not get_bool(proxy_on, "proxy", "enabled", default=False):
            errors.append(f"{board}: proxy dedupe-on config must have `proxy.enabled=true`")

        if get_bool(proxy_off, "dedupe", "enabled", default=True):
            errors.append(f"{board}: proxy dedupe-off file has `dedupe.enabled=true`")
        if not get_bool(proxy_on, "dedupe", "enabled", default=False):
            errors.append(f"{board}: proxy dedupe-on file has `dedupe.enabled=false`")

        if get_bool(proxy_off, "output", "vault_sync", "enabled", default=False):
            errors.append(f"{board}: proxy dedupe-off must keep `output.vault_sync.enabled=false`")
        if get_bool(proxy_on, "output", "vault_sync", "enabled", default=False):
            errors.append(f"{board}: proxy dedupe-on must keep `output.vault_sync.enabled=false`")

    return errors, notes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate standardized board test configs.")
    parser.add_argument(
        "--board",
        action="append",
        default=[],
        help="Board to validate (repeatable). Defaults to standard board set.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    boards = args.board or STANDARD_BOARDS

    all_errors: list[str] = []
    all_notes: list[str] = []

    print("Standard config validation")
    print(f"Repo: {REPO_ROOT}")
    print(f"Boards: {', '.join(boards)}")
    print("")

    for board in boards:
        errors, notes = validate_board(board)
        all_errors.extend(errors)
        all_notes.extend(notes)
        status = "PASS" if not errors else "FAIL"
        print(f"[{status}] {board}")

    if all_notes:
        print("\nNotes:")
        for note in all_notes:
            print(f"- {note}")

    if all_errors:
        print("\nErrors:")
        for error in all_errors:
            print(f"- {error}")
        return 1

    print("\nAll standardized config checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
