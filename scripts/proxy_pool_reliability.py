#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = "boards/glassdoor/config/reliability_smoke.yaml"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_slug() -> str:
    return _utc_now().strftime("%Y%m%d_%H%M%S")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _mask_host(host: str) -> str:
    parts = host.split(".")
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return ".".join(parts[:3] + ["x"])

    h = host.strip()
    if len(h) <= 6:
        return h[:1] + "…"
    return f"{h[:3]}…{h[-2:]}"


def _parse_indexes(raw: str) -> set[int]:
    idxs: set[int] = set()
    for part in [p.strip() for p in raw.split(",") if p.strip()]:
        idxs.add(int(part))
    return idxs


def _coordination_gate(*, skip: bool) -> None:
    if skip:
        return

    in_progress_dir = Path.home() / ".claude-context/orchestrator/queue/in-progress"
    if not in_progress_dir.exists():
        return

    conflicts: list[str] = []
    for p in sorted(in_progress_dir.glob("task-*.md")):
        name = p.name.lower()
        if "glassdoor" not in name:
            continue
        if "isp-proxy-pool-reliability" in name:
            continue
        conflicts.append(p.name)

    if conflicts:
        joined = "\n".join(f"- {c}" for c in conflicts)
        raise SystemExit(
            "Coordination gate: found other in-progress Glassdoor tasks. "
            "Do not run concurrent Glassdoor loops.\n\n"
            f"{joined}\n\n"
            "Re-run with `--skip-coordination-gate` only if you are sure nothing else is running."
        )


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
class AttemptResult:
    run_index: int
    phase: str  # filter | measured
    started_at_utc: str
    duration_seconds: float
    exit_code: int
    stdout_path: str
    run_metrics_path: Optional[str]
    pass_: bool
    jobs_unique_collected: int
    counters: dict[str, int]


def _parse_endpoints(raw: str) -> list[ProxyEndpoint]:
    endpoints: list[ProxyEndpoint] = []
    for i, item in enumerate([p.strip() for p in raw.split(",") if p.strip()], start=1):
        # Supported formats:
        # - host:port:username:password
        # - host:port (falls back to PROXY_USERNAME/PROXY_PASSWORD)
        #
        # Allow IPv6 by splitting from the right.
        parts = item.rsplit(":", 3)
        if len(parts) == 2:
            host, port = parts
            username = os.environ.get("PROXY_USERNAME") or ""
            password = os.environ.get("PROXY_PASSWORD") or ""
            if not username or not password:
                raise ValueError(
                    f"ISP_PROXY_ENDPOINTS entry #{i} is missing credentials and PROXY_USERNAME/PROXY_PASSWORD are not set"
                )
        elif len(parts) == 4:
            host, port, username, password = parts
        else:
            raise ValueError(
                f"ISP_PROXY_ENDPOINTS entry #{i} is malformed (expected host:port or host:port:username:password)"
            )
        if not host or not port:
            raise ValueError(f"ISP_PROXY_ENDPOINTS entry #{i} is missing host/port")
        endpoints.append(ProxyEndpoint(host=host, port=port, username=username, password=password))
    return endpoints


def _load_summary_json(path: Path) -> list[tuple[int, str, list[AttemptResult]]]:
    data = _read_json(path)
    proxies = data.get("proxies") or []
    out: list[tuple[int, str, list[AttemptResult]]] = []
    for p in proxies:
        idx = int(p.get("index") or 0)
        masked = str(p.get("masked_endpoint") or "")
        attempts: list[AttemptResult] = []
        for a in (p.get("attempts") or []):
            attempts.append(
                AttemptResult(
                    run_index=int(a.get("run_index") or 0),
                    phase=str(a.get("phase") or ""),
                    started_at_utc=str(a.get("started_at_utc") or ""),
                    duration_seconds=float(a.get("duration_seconds") or 0.0),
                    exit_code=int(a.get("exit_code") or 0),
                    stdout_path=str(a.get("stdout_path") or ""),
                    run_metrics_path=(str(a.get("run_metrics_path")) if a.get("run_metrics_path") else None),
                    pass_=bool(a.get("pass_") or False),
                    jobs_unique_collected=int(a.get("jobs_unique_collected") or 0),
                    counters=dict(a.get("counters") or {}),
                )
            )
        out.append((idx, masked, attempts))
    return out


def _merge_summaries(summary_paths: list[Path]) -> list[tuple[int, str, list[AttemptResult]]]:
    merged: dict[int, tuple[str, list[AttemptResult]]] = {}
    for path in summary_paths:
        for idx, masked, attempts in _load_summary_json(path):
            if idx <= 0:
                continue
            if idx not in merged:
                merged[idx] = (masked, list(attempts))
                continue
            cur_masked, cur_attempts = merged[idx]
            merged[idx] = (masked or cur_masked, cur_attempts + list(attempts))
    out: list[tuple[int, str, list[AttemptResult]]] = []
    for idx in sorted(merged.keys()):
        masked, attempts = merged[idx]
        out.append((idx, masked, attempts))
    return out


def _find_new_metrics(board_dir: Path, before: set[Path], started_monotonic: float) -> Optional[Path]:
    out_dir = board_dir / "output"
    if not out_dir.exists():
        return None

    after = set(out_dir.glob("run_metrics_*.json"))
    created = sorted(after - before, key=lambda p: p.stat().st_mtime)
    if created:
        return created[-1]

    candidates = sorted(after, key=lambda p: p.stat().st_mtime)
    if not candidates:
        return None

    elapsed = time.monotonic() - started_monotonic
    threshold = time.time() - max(elapsed + 3.0, 0.0)
    for p in reversed(candidates):
        if p.stat().st_mtime >= threshold:
            return p
    return candidates[-1]


def _scrub_stdout(*, text: str, endpoint: ProxyEndpoint) -> str:
    scrubbed = text
    for secret in [endpoint.username, endpoint.password]:
        if secret:
            scrubbed = scrubbed.replace(secret, "***")

    if endpoint.host:
        scrubbed = scrubbed.replace(endpoint.host, _mask_host(endpoint.host))
        scrubbed = scrubbed.replace(f"{endpoint.host}:{endpoint.port}", f"{_mask_host(endpoint.host)}:{endpoint.port}")
    return scrubbed


def _run_glassdoor_once(
    *,
    endpoint: ProxyEndpoint,
    config_path: str,
    artifact_dir: Path,
    runner_path: Path,
    run_index: int,
    phase: str,
    dry_run: bool,
) -> AttemptResult:
    board_dir = REPO_ROOT / "boards" / "glassdoor"
    out_dir = board_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    stdout_path = artifact_dir / f"run_{run_index:02d}.stdout.log"
    started_at = _utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")
    started_monotonic = time.monotonic()

    before = set(out_dir.glob("run_metrics_*.json"))
    artifact_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        stdout_path.write_text(
            f"[dry-run] Would run: {runner_path} glassdoor {config_path}\n",
            encoding="utf-8",
        )
        return AttemptResult(
            run_index=run_index,
            phase=phase,
            started_at_utc=started_at,
            duration_seconds=0.0,
            exit_code=0,
            stdout_path=str(stdout_path),
            run_metrics_path=None,
            pass_=False,
            jobs_unique_collected=0,
            counters={},
        )

    env = dict(os.environ)
    env["PROXY_HOST"] = endpoint.host
    env["PROXY_PORT"] = endpoint.port
    env["PROXY_USERNAME"] = endpoint.username
    env["PROXY_PASSWORD"] = endpoint.password
    env["PYTHONUNBUFFERED"] = "1"

    cmd: list[str] = [str(runner_path), "glassdoor", config_path]

    p = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    duration = time.monotonic() - started_monotonic

    stdout_path.write_text(
        _scrub_stdout(text=p.stdout or "", endpoint=endpoint),
        encoding="utf-8",
        errors="replace",
    )

    metrics_path = _find_new_metrics(board_dir, before, started_monotonic)

    jobs_unique = 0
    counters: dict[str, int] = {}
    if metrics_path and metrics_path.exists():
        try:
            data = _read_json(metrics_path)
            gauges = data.get("gauges") or {}
            jobs_unique = _safe_int(gauges.get("jobs_unique_collected") or 0)
            raw_counters = data.get("counters") or {}
            for k in [
                "blocked_pages",
                "captcha_encounters",
                "capsolver_solved",
                "solver_failures",
                "captcha_solved",
            ]:
                v = raw_counters.get(k)
                if v is not None:
                    counters[k] = _safe_int(v)
        except Exception:
            metrics_path = None

    pass_ = jobs_unique >= 1
    return AttemptResult(
        run_index=run_index,
        phase=phase,
        started_at_utc=started_at,
        duration_seconds=float(duration),
        exit_code=int(p.returncode),
        stdout_path=str(stdout_path),
        run_metrics_path=str(metrics_path) if metrics_path else None,
        pass_=bool(pass_),
        jobs_unique_collected=int(jobs_unique),
        counters=counters,
    )


def _sum_counter(attempts: list[AttemptResult], key: str) -> int:
    return sum(int(a.counters.get(key, 0) or 0) for a in attempts)


def _median(values: list[float]) -> Optional[float]:
    if not values:
        return None
    values = sorted(values)
    mid = len(values) // 2
    if len(values) % 2 == 1:
        return float(values[mid])
    return float((values[mid - 1] + values[mid]) / 2.0)


def _fmt_rate(successes: int, total: int) -> str:
    if total <= 0:
        return "0.0%"
    return f"{(successes / total) * 100.0:.1f}%"


def _render_report(
    *,
    config_path: str,
    artifact_dir: Path,
    filter_runs: int,
    measured_runs: int,
    sleep_seconds: float,
    keep_threshold: float,
    keep_min_runs: int,
    results: list[tuple[int, ProxyEndpoint, list[AttemptResult]]],
) -> str:
    generated = _utc_now().strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []
    lines.append("# ISP Proxy Pool Glassdoor Reliability (per proxy)")
    lines.append("")
    lines.append(f"**Generated:** {generated}  ")
    lines.append(f"**Config:** `{config_path}`  ")
    lines.append("**Pass Criteria:** `jobs_unique_collected >= 1`  ")
    lines.append(f"**Runs:** filter={filter_runs}, measured={measured_runs}, sleep={sleep_seconds:.0f}s  ")
    lines.append(f"**Artifacts:** `{artifact_dir}`")
    lines.append("")

    if not results:
        lines.append("_No results (did you set `ISP_PROXY_ENDPOINTS`?)_")
        lines.append("")
        return "\n".join(lines) + "\n"

    def phase_summary(attempts: list[AttemptResult], phase: str) -> tuple[int, int, str, dict[str, int], Optional[float]]:
        a = [x for x in attempts if x.phase == phase]
        succ = sum(1 for x in a if x.pass_)
        total = len(a)
        counters = {
            "blocked_pages": _sum_counter(a, "blocked_pages"),
            "captcha_encounters": _sum_counter(a, "captcha_encounters"),
            "capsolver_solved": _sum_counter(a, "capsolver_solved"),
            "solver_failures": _sum_counter(a, "solver_failures"),
        }
        durations = [float(x.duration_seconds) for x in a if x.duration_seconds > 0]
        return (succ, total, _fmt_rate(succ, total), counters, _median(durations))

    filter_rows: list[tuple[int, str, int, int, str, dict[str, int], Optional[float]]] = []
    measured_rows: list[tuple[int, str, int, int, str, dict[str, int], Optional[float]]] = []
    for idx, ep, attempts in results:
        f_s, f_t, f_r, f_c, f_med = phase_summary(attempts, "filter")
        m_s, m_t, m_r, m_c, m_med = phase_summary(attempts, "measured")
        filter_rows.append((idx, ep.masked_label, f_s, f_t, f_r, f_c, f_med))
        measured_rows.append((idx, ep.masked_label, m_s, m_t, m_r, m_c, m_med))

    def rank_key(row: tuple[int, str, int, int, str, dict[str, int], Optional[float]]) -> tuple[float, int, int]:
        _idx, _label, succ, total, _rate, counters, _med = row
        rate = (succ / total) if total else 0.0
        return (
            rate,
            -int(counters.get("blocked_pages", 0) or 0),
            -int(counters.get("captcha_encounters", 0) or 0),
        )

    lines.append("## Results (Filter Phase)")
    lines.append("")
    lines.append("| # | Proxy (masked) | Pass | Rate | blocked | captcha | solved | solver_fail | median_dur_s |")
    lines.append("|---:|---|---:|---:|---:|---:|---:|---:|---:|")
    for idx, label, succ, total, rate, counters, med in sorted(filter_rows, key=rank_key, reverse=True):
        lines.append(
            "| {i} | `{label}` | {succ}/{total} | {rate} | {b} | {c} | {s} | {f} | {med} |".format(
                i=idx,
                label=label,
                succ=succ,
                total=total,
                rate=rate,
                b=int(counters.get("blocked_pages", 0) or 0),
                c=int(counters.get("captcha_encounters", 0) or 0),
                s=int(counters.get("capsolver_solved", 0) or 0),
                f=int(counters.get("solver_failures", 0) or 0),
                med=f"{med:.1f}" if med is not None else "",
            )
        )
    lines.append("")

    if measured_runs > 0:
        lines.append("## Results (Measured Phase)")
        lines.append("")
        lines.append("| # | Proxy (masked) | Pass | Rate | blocked | captcha | solved | solver_fail | median_dur_s |")
        lines.append("|---:|---|---:|---:|---:|---:|---:|---:|---:|")
        for idx, label, succ, total, rate, counters, med in sorted(measured_rows, key=rank_key, reverse=True):
            if total <= 0:
                continue
            lines.append(
                "| {i} | `{label}` | {succ}/{total} | {rate} | {b} | {c} | {s} | {f} | {med} |".format(
                    i=idx,
                    label=label,
                    succ=succ,
                    total=total,
                    rate=rate,
                    b=int(counters.get("blocked_pages", 0) or 0),
                    c=int(counters.get("captcha_encounters", 0) or 0),
                    s=int(counters.get("capsolver_solved", 0) or 0),
                    f=int(counters.get("solver_failures", 0) or 0),
                    med=f"{med:.1f}" if med is not None else "",
                )
            )
        lines.append("")

    lines.append("## Recommendation")
    lines.append("")

    keep: list[str] = []
    if measured_runs >= keep_min_runs:
        for idx, label, succ, total, _rate, _counters, _med in sorted(measured_rows, key=rank_key, reverse=True):
            if total < keep_min_runs:
                continue
            rate = (succ / total) if total else 0.0
            if rate >= keep_threshold:
                keep.append(f"{idx} (`{label}`)")
    if keep:
        lines.append(f"- **Keep:** {', '.join(keep)}")
    else:
        if measured_runs >= keep_min_runs:
            lines.append(
                f"- **Keep:** none meet threshold (need ≥ {keep_min_runs} measured runs and ≥ {keep_threshold:.0%} success rate)"
            )
            lines.append("- **Next:** consider switching proxy provider/pool if this persists.")
        else:
            lines.append(
                f"- **Keep:** not enough measured runs for a keep decision (need ≥ {keep_min_runs}; got {measured_runs})."
            )
            lines.append("- **Next:** run a measured phase on the top 1–2 proxies from filter.")
    lines.append("")

    lines.append("## How To Re-Run")
    lines.append("")
    lines.append("Phase A (filter across all proxies):")
    lines.append("```bash")
    lines.append("python3 scripts/proxy_pool_reliability.py --filter-runs 5 --sleep-seconds 45")
    lines.append("```")
    lines.append("")
    lines.append("Phase B (measured for a subset):")
    lines.append("```bash")
    lines.append("python3 scripts/proxy_pool_reliability.py --only-indexes 2,4 --measured-runs 10 --sleep-seconds 45")
    lines.append("```")
    lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Benchmark Glassdoor reliability per ISP proxy endpoint (repeated runs per proxy)."
    )
    ap.add_argument(
        "--config-path",
        default=DEFAULT_CONFIG_PATH,
        help="Glassdoor YAML config to use (repo-root-relative).",
    )
    ap.add_argument(
        "--filter-runs",
        type=int,
        default=5,
        help="Phase A: quick filter runs per proxy (default: 5). Use 0 to skip.",
    )
    ap.add_argument(
        "--measured-runs",
        type=int,
        default=0,
        help="Phase B: measured runs per proxy (default: 0).",
    )
    ap.add_argument(
        "--only-indexes",
        default="",
        help="Comma-separated 1-based proxy indexes to run (e.g. '2,4'). Default runs all.",
    )
    ap.add_argument(
        "--sleep-seconds",
        type=float,
        default=45.0,
        help="Sleep between runs (default: 45).",
    )
    ap.add_argument(
        "--artifact-dir",
        default=str(
            REPO_ROOT
            / "docs/reliability/artifacts/isp_proxy_pool_reliability"
            / f"reliability_{_utc_now_slug()}"
        ),
        help="Directory to write stdout logs and JSON summary.",
    )
    ap.add_argument(
        "--report-path",
        default=str(REPO_ROOT / "docs/reliability/isp_proxy_pool_glassdoor_reliability.md"),
        help="Where to write the markdown report (overwritten).",
    )
    ap.add_argument(
        "--runner",
        default=str(REPO_ROOT / "scripts/run_board.sh"),
        help="Path to run_board.sh",
    )
    ap.add_argument(
        "--keep-threshold",
        type=float,
        default=0.80,
        help="Success-rate threshold to recommend keeping a proxy (default: 0.80).",
    )
    ap.add_argument(
        "--keep-min-runs",
        type=int,
        default=10,
        help="Minimum measured runs required for a keep recommendation (default: 10).",
    )
    ap.add_argument(
        "--skip-coordination-gate",
        action="store_true",
        help="Skip orchestrator in-progress task check (not recommended).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not execute Glassdoor; just parse endpoints and write an empty report/artifacts.",
    )
    ap.add_argument(
        "--merge-summary-jsons",
        default="",
        help="Comma-separated paths to existing summary.json files to merge into a single report (no live runs).",
    )
    args = ap.parse_args()

    if args.merge_summary_jsons.strip():
        summary_paths = [Path(p.strip()) for p in args.merge_summary_jsons.split(",") if p.strip()]
        if not summary_paths:
            raise SystemExit("--merge-summary-jsons provided but no paths parsed")
        for p in summary_paths:
            if not p.exists():
                raise SystemExit(f"summary.json not found: {p}")

        artifact_dir = Path(args.artifact_dir)
        report_path = Path(args.report_path)
        config_path = str(args.config_path)

        merged_attempts = _merge_summaries(summary_paths)
        results: list[tuple[int, ProxyEndpoint, list[AttemptResult]]] = []
        for idx, masked, attempts in merged_attempts:
            # Placeholder endpoint for rendering; only masked_label is used in the report.
            if ":" in masked:
                host, port = masked.split(":", 1)
            else:
                host, port = masked, ""
            ep = ProxyEndpoint(host=host, port=port, username="", password="")
            results.append((idx, ep, attempts))

        artifact_dir.mkdir(parents=True, exist_ok=True)
        merged_summary_path = artifact_dir / "summary.merged.json"
        merged_summary = {
            "generated_at_utc": _utc_now().isoformat(),
            "board": "glassdoor",
            "config_path": config_path,
            "merged_from": [str(p) for p in summary_paths],
            "proxies": [
                {
                    "index": idx,
                    "masked_endpoint": ep.masked_label,
                    "attempts": [asdict(a) for a in attempts],
                }
                for (idx, ep, attempts) in results
            ],
        }
        merged_summary_path.write_text(
            json.dumps(merged_summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        report_md = _render_report(
            config_path=config_path,
            artifact_dir=artifact_dir,
            filter_runs=int(args.filter_runs),
            measured_runs=int(args.measured_runs),
            sleep_seconds=float(args.sleep_seconds),
            keep_threshold=float(args.keep_threshold),
            keep_min_runs=int(args.keep_min_runs),
            results=results,
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_md, encoding="utf-8")
        (artifact_dir / "report.md").write_text(report_md, encoding="utf-8")

        print(f"Wrote merged report: {report_path}")
        print(f"Wrote merge artifacts: {artifact_dir}")
        return 0

    _coordination_gate(skip=bool(args.skip_coordination_gate or args.dry_run))

    raw = os.environ.get("ISP_PROXY_ENDPOINTS", "").strip()
    if not raw:
        host = (os.environ.get("PROXY_HOST") or "").strip()
        port = (os.environ.get("PROXY_PORT") or "").strip()
        username = os.environ.get("PROXY_USERNAME") or ""
        password = os.environ.get("PROXY_PASSWORD") or ""
        if host and port and username and password:
            raw = f"{host}:{port}:{username}:{password}"
            print("WARN: ISP_PROXY_ENDPOINTS is unset; falling back to PROXY_* env vars as a single-endpoint pool.")
        else:
            raise SystemExit(
                "ISP_PROXY_ENDPOINTS is not set (expected comma-separated host:port:username:password). "
                "Alternatively set PROXY_HOST/PROXY_PORT/PROXY_USERNAME/PROXY_PASSWORD for a single-endpoint fallback."
            )

    endpoints = _parse_endpoints(raw)
    only: Optional[set[int]] = _parse_indexes(args.only_indexes) if args.only_indexes.strip() else None

    selected: list[tuple[int, ProxyEndpoint]] = []
    for idx, ep in enumerate(endpoints, start=1):
        if only and idx not in only:
            continue
        selected.append((idx, ep))
    if not selected:
        raise SystemExit("No proxies selected (check --only-indexes).")

    artifact_dir = Path(args.artifact_dir)
    report_path = Path(args.report_path)
    runner_path = Path(args.runner)
    config_path = str(args.config_path)

    results: list[tuple[int, ProxyEndpoint, list[AttemptResult]]] = []
    for pos, (idx, ep) in enumerate(selected, start=1):
        per_proxy_dir = artifact_dir / f"proxy_{idx:02d}_{_mask_host(ep.host)}"
        attempts: list[AttemptResult] = []

        run_index = 1
        for _ in range(max(0, int(args.filter_runs))):
            a = _run_glassdoor_once(
                endpoint=ep,
                config_path=config_path,
                artifact_dir=per_proxy_dir,
                runner_path=runner_path,
                run_index=run_index,
                phase="filter",
                dry_run=bool(args.dry_run),
            )
            attempts.append(a)
            print(
                f"[{pos}/{len(selected)}] proxy #{idx} {ep.masked_label} | "
                f"filter run {run_index}/{args.filter_runs} | "
                f"{'PASS' if a.pass_ else 'FAIL'} (jobs={a.jobs_unique_collected})"
            )
            run_index += 1
            if args.sleep_seconds > 0 and (run_index <= int(args.filter_runs)):
                time.sleep(float(args.sleep_seconds))

        for _ in range(max(0, int(args.measured_runs))):
            a = _run_glassdoor_once(
                endpoint=ep,
                config_path=config_path,
                artifact_dir=per_proxy_dir,
                runner_path=runner_path,
                run_index=run_index,
                phase="measured",
                dry_run=bool(args.dry_run),
            )
            attempts.append(a)
            measured_idx = run_index - max(0, int(args.filter_runs))
            print(
                f"[{pos}/{len(selected)}] proxy #{idx} {ep.masked_label} | "
                f"measured run {measured_idx}/{args.measured_runs} | "
                f"{'PASS' if a.pass_ else 'FAIL'} (jobs={a.jobs_unique_collected})"
            )
            run_index += 1
            if args.sleep_seconds > 0 and (measured_idx < int(args.measured_runs)):
                time.sleep(float(args.sleep_seconds))

        results.append((idx, ep, attempts))

    artifact_dir.mkdir(parents=True, exist_ok=True)
    summary_path = artifact_dir / "summary.json"
    summary = {
        "generated_at_utc": _utc_now().isoformat(),
        "board": "glassdoor",
        "config_path": config_path,
        "filter_runs": int(args.filter_runs),
        "measured_runs": int(args.measured_runs),
        "sleep_seconds": float(args.sleep_seconds),
        "keep_threshold": float(args.keep_threshold),
        "keep_min_runs": int(args.keep_min_runs),
        "proxies": [
            {
                "index": idx,
                "masked_endpoint": ep.masked_label,
                "attempts": [asdict(a) for a in attempts],
            }
            for (idx, ep, attempts) in results
        ],
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report_md = _render_report(
        config_path=config_path,
        artifact_dir=artifact_dir,
        filter_runs=int(args.filter_runs),
        measured_runs=int(args.measured_runs),
        sleep_seconds=float(args.sleep_seconds),
        keep_threshold=float(args.keep_threshold),
        keep_min_runs=int(args.keep_min_runs),
        results=results,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_md, encoding="utf-8")
    (artifact_dir / "report.md").write_text(report_md, encoding="utf-8")

    print(f"Wrote report: {report_path}")
    print(f"Wrote artifacts: {artifact_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
