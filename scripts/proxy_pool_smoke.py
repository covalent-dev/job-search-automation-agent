#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_slug() -> str:
    return _utc_now().strftime("%Y%m%d_%H%M%S")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _mask_host(host: str) -> str:
    # IPv4: mask last octet (A.B.C.x)
    parts = host.split(".")
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return ".".join(parts[:3] + ["x"])

    # Hostname: keep small prefix/suffix only
    h = host.strip()
    if len(h) <= 6:
        return h[:1] + "…"
    return f"{h[:3]}…{h[-2:]}"


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


@dataclass(frozen=True)
class ProxyEndpoint:
    host: str
    port: str
    username: str
    password: str

    @property
    def masked_label(self) -> str:
        return f"{_mask_host(self.host)}:{self.port}"


@dataclass(frozen=True)
class BoardAttempt:
    board: str
    exit_code: int
    duration_seconds: float
    stdout_path: Path
    run_metrics_path: Optional[Path]
    jobs_unique_collected: int
    counters: dict[str, int]

    @property
    def pass_(self) -> bool:
        return self.jobs_unique_collected >= 1


def _parse_endpoints(raw: str) -> list[ProxyEndpoint]:
    endpoints: list[ProxyEndpoint] = []
    for i, item in enumerate([p.strip() for p in raw.split(",") if p.strip()], start=1):
        # Allow IPv6 by splitting from the right
        parts = item.rsplit(":", 3)
        if len(parts) != 4:
            raise ValueError(
                f"ISP_PROXY_ENDPOINTS entry #{i} is malformed (expected host:port:username:password)"
            )
        host, port, username, password = parts
        if not host or not port:
            raise ValueError(f"ISP_PROXY_ENDPOINTS entry #{i} is missing host/port")
        endpoints.append(ProxyEndpoint(host=host, port=port, username=username, password=password))
    return endpoints


def _find_new_metrics(board_dir: Path, before: set[Path], started_monotonic: float) -> Optional[Path]:
    out_dir = board_dir / "output"
    if not out_dir.exists():
        return None

    after = set(out_dir.glob("run_metrics_*.json"))
    created = sorted(after - before, key=lambda p: p.stat().st_mtime)
    if created:
        return created[-1]

    # Fallback: select most recent metrics file that looks like it was written after the run began.
    candidates = sorted(after, key=lambda p: p.stat().st_mtime)
    if not candidates:
        return None

    # Convert monotonic to a coarse wall-clock threshold via "now - elapsed".
    elapsed = time.monotonic() - started_monotonic
    threshold = time.time() - max(elapsed + 3.0, 0.0)
    for p in reversed(candidates):
        if p.stat().st_mtime >= threshold:
            return p
    return candidates[-1]


def _run_board_once(
    *,
    endpoint: ProxyEndpoint,
    board: str,
    config_path: str,
    artifact_dir: Path,
    runner_path: Path,
) -> BoardAttempt:
    board_dir = REPO_ROOT / "boards" / board
    out_dir = board_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    before = set(out_dir.glob("run_metrics_*.json"))
    stdout_path = artifact_dir / f"{board}.stdout.log"

    env = dict(os.environ)
    env["PROXY_HOST"] = endpoint.host
    env["PROXY_PORT"] = endpoint.port
    env["PROXY_USERNAME"] = endpoint.username
    env["PROXY_PASSWORD"] = endpoint.password
    env["PYTHONUNBUFFERED"] = "1"

    started = time.monotonic()
    cmd: list[str] = [str(runner_path), board, config_path]

    # Indeed smoke config is headed; if there's no DISPLAY but xvfb-run exists, use it.
    if board == "indeed" and not env.get("DISPLAY"):
        xvfb = shutil.which("xvfb-run")  # type: ignore[name-defined]
        if xvfb:
            cmd = [xvfb, "-a"] + cmd

    artifact_dir.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("w", encoding="utf-8") as f:
        p = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            env=env,
            stdout=f,
            stderr=subprocess.STDOUT,
            text=True,
        )
    duration = time.monotonic() - started

    metrics_path = _find_new_metrics(board_dir, before, started)

    jobs_unique = 0
    counters: dict[str, int] = {}
    if metrics_path and metrics_path.exists():
        try:
            data = _read_json(metrics_path)
            gauges = data.get("gauges") or {}
            jobs_unique = _safe_int(gauges.get("jobs_unique_collected") or 0)
            raw_counters = data.get("counters") or {}
            for k in ["blocked_pages", "captcha_encounters", "capsolver_solved", "solver_failures"]:
                counters[k] = _safe_int(raw_counters.get(k) or 0)
        except Exception:
            metrics_path = None

    return BoardAttempt(
        board=board,
        exit_code=int(p.returncode),
        duration_seconds=float(duration),
        stdout_path=stdout_path,
        run_metrics_path=metrics_path,
        jobs_unique_collected=int(jobs_unique),
        counters=counters,
    )


def _format_attempt_cell(a: Optional[BoardAttempt]) -> str:
    if not a:
        return "❌ (no metrics)"
    status = "✅" if a.pass_ else "❌"
    blocked = a.counters.get("blocked_pages", 0)
    captcha = a.counters.get("captcha_encounters", 0)
    solved = a.counters.get("capsolver_solved", 0)
    fails = a.counters.get("solver_failures", 0)
    return f"{status} (jobs={a.jobs_unique_collected}, blocked={blocked}, captcha={captcha}, solved={solved}, fails={fails})"


def _best_proxy(
    results: list[tuple[ProxyEndpoint, BoardAttempt, BoardAttempt]],
    *,
    board: str,
) -> list[ProxyEndpoint]:
    idx = 1 if board == "indeed" else 2
    passed = [r for r in results if (r[idx].pass_ if r[idx] else False)]
    if not passed:
        return []

    def key_fn(t: tuple[ProxyEndpoint, BoardAttempt, BoardAttempt]) -> tuple[int, int, int]:
        attempt = t[idx]
        return (
            attempt.jobs_unique_collected,
            -attempt.counters.get("blocked_pages", 0),
            -attempt.counters.get("captcha_encounters", 0),
        )

    passed.sort(key=key_fn, reverse=True)
    top_score = key_fn(passed[0])
    return [p for (p, *_a) in passed if key_fn((p, *_a)) == top_score]


def _write_report(
    *,
    report_path: Path,
    artifact_dir: Path,
    results: list[tuple[ProxyEndpoint, BoardAttempt, BoardAttempt]],
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)

    best_indeed = _best_proxy(results, board="indeed")
    best_glassdoor = _best_proxy(results, board="glassdoor")

    lines: list[str] = []
    lines.append("# ISP Proxy Pool Smoke Test (Indeed + Glassdoor)")
    lines.append("")
    lines.append(f"**Generated:** {_utc_now().strftime('%Y-%m-%d %H:%M UTC')}  ")
    lines.append("**Pass Criteria:** `jobs_unique_collected >= 1`  ")
    lines.append(f"**Artifacts:** `{artifact_dir}`")
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append("| Proxy | Endpoint (masked) | Indeed | Glassdoor |")
    lines.append("|---:|---|---|---|")
    for i, (ep, indeed_a, glass_a) in enumerate(results, start=1):
        lines.append(
            "| {i} | `{ep}` | {indeed} | {glass} |".format(
                i=i,
                ep=ep.masked_label,
                indeed=_format_attempt_cell(indeed_a),
                glass=_format_attempt_cell(glass_a),
            )
        )
    lines.append("")
    lines.append("## Recommendation")
    lines.append("")

    if best_indeed:
        choices = ", ".join(f"`{p.masked_label}`" for p in best_indeed)
        lines.append(f"- **Indeed:** keep {choices}")
    else:
        lines.append("- **Indeed:** no passing proxies in this pool (all `jobs_unique_collected == 0`)")

    if best_glassdoor:
        choices = ", ".join(f"`{p.masked_label}`" for p in best_glassdoor)
        lines.append(f"- **Glassdoor:** keep {choices}")
    else:
        lines.append("- **Glassdoor:** no passing proxies in this pool (all `jobs_unique_collected == 0`)")

    lines.append("")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke test a proxy pool on Indeed + Glassdoor.")
    ap.add_argument(
        "--report-path",
        default=str(REPO_ROOT / "docs/reliability/isp_proxy_pool_smoke.md"),
        help="Where to write the markdown report.",
    )
    ap.add_argument(
        "--artifact-dir",
        default=str(REPO_ROOT / "docs/reliability/artifacts/isp_proxy_pool_smoke" / f"smoke_{_utc_now_slug()}"),
        help="Directory to write stdout logs.",
    )
    ap.add_argument(
        "--runner",
        default=str(REPO_ROOT / "scripts/run_board.sh"),
        help="Path to run_board.sh",
    )
    args = ap.parse_args()

    raw = os.environ.get("ISP_PROXY_ENDPOINTS", "").strip()
    if not raw:
        raise SystemExit("ISP_PROXY_ENDPOINTS is not set (expected comma-separated host:port:username:password)")

    endpoints = _parse_endpoints(raw)
    artifact_dir = Path(args.artifact_dir)
    report_path = Path(args.report_path)
    runner_path = Path(args.runner)

    results: list[tuple[ProxyEndpoint, BoardAttempt, BoardAttempt]] = []
    for i, ep in enumerate(endpoints, start=1):
        per_proxy_dir = artifact_dir / f"proxy_{i:02d}_{_mask_host(ep.host)}"
        indeed_attempt = _run_board_once(
            endpoint=ep,
            board="indeed",
            config_path="boards/indeed/config/smoke_test.yaml",
            artifact_dir=per_proxy_dir,
            runner_path=runner_path,
        )
        glassdoor_attempt = _run_board_once(
            endpoint=ep,
            board="glassdoor",
            config_path="boards/glassdoor/config/smoke_test.yaml",
            artifact_dir=per_proxy_dir,
            runner_path=runner_path,
        )
        results.append((ep, indeed_attempt, glassdoor_attempt))

        print(
            f"[{i}/{len(endpoints)}] {ep.masked_label} | "
            f"Indeed: {'PASS' if indeed_attempt.pass_ else 'FAIL'} "
            f"(jobs={indeed_attempt.jobs_unique_collected}) | "
            f"Glassdoor: {'PASS' if glassdoor_attempt.pass_ else 'FAIL'} "
            f"(jobs={glassdoor_attempt.jobs_unique_collected})"
        )

    _write_report(report_path=report_path, artifact_dir=artifact_dir, results=results)
    print(f"Wrote report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
