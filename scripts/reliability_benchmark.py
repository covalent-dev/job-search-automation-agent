#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
import os
import sys
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


def _pct(n: float) -> str:
    return f"{n * 100:.1f}%"


def _wilson_interval(successes: int, n: int, *, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    phat = successes / n
    denom = 1.0 + (z * z) / n
    center = (phat + (z * z) / (2.0 * n)) / denom
    radius = (z * math.sqrt((phat * (1.0 - phat) + (z * z) / (4.0 * n)) / n)) / denom
    return (max(0.0, center - radius), min(1.0, center + radius))


def _median(values: list[float]) -> Optional[float]:
    if not values:
        return None
    values = sorted(values)
    mid = len(values) // 2
    if len(values) % 2 == 1:
        return float(values[mid])
    return float((values[mid - 1] + values[mid]) / 2.0)


def _percentile(values: list[float], p: float) -> Optional[float]:
    if not values:
        return None
    if p <= 0:
        return float(min(values))
    if p >= 100:
        return float(max(values))
    values = sorted(values)
    k = (len(values) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(values[int(k)])
    d0 = values[int(f)] * (c - k)
    d1 = values[int(c)] * (k - f)
    return float(d0 + d1)


def _longest_streak(flags: list[bool], *, value: bool) -> int:
    best = 0
    cur = 0
    for f in flags:
        if f == value:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _tail_lines(path: Path, *, max_lines: int = 120) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-max_lines:]
    except Exception:
        return []


def _infer_failure_note(stdout_path: Path) -> Optional[str]:
    tail = "\n".join(_tail_lines(stdout_path, max_lines=120)).lower()
    if not tail:
        return None

    patterns = [
        ("timeout", "timeout"),
        ("navigation failed", "navigation failures"),
        ("just a moment", "verification loop (Just a moment)"),
        ("additional verification", "additional verification loop"),
        ("security check", "security check loop"),
        ("challenge did not auto-resolve", "challenge did not auto-resolve"),
        ("captcha solver failed", "captcha solver failed"),
        ("browser restart for proxy rotation failed", "proxy rotation/browser restart failed"),
    ]
    for needle, label in patterns:
        if needle in tail:
            return label
    return None


@dataclass
class AttemptResult:
    run_index: int
    phase: str  # warmup | measured
    started_at_utc: str
    duration_seconds: float
    metrics_duration_seconds: Optional[float]
    exit_code: int
    stdout_path: str
    run_metrics_path: Optional[str]
    pass_: bool
    jobs_unique_collected: int
    counters: dict[str, int]
    timings_ms: dict[str, int]
    result: Optional[str]
    failure_stage: Optional[str]
    failure_kind: Optional[str]
    exception_class: Optional[str]
    exception_message: Optional[str]
    last_url: Optional[str]
    failure_reason: Optional[str]
    failure_note: Optional[str]


def _find_latest_run_metrics(board_dir: Path) -> Optional[Path]:
    out_dir = board_dir / "output"
    if not out_dir.exists():
        return None
    candidates = sorted(out_dir.glob("run_metrics_*.json"), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def _count_by_reason(results: list[AttemptResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in results:
        if r.phase != "measured":
            continue
        key = r.failure_kind or r.failure_reason or ("pass" if r.pass_ else "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _count_by_stage(results: list[AttemptResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in results:
        if r.phase != "measured" or r.pass_:
            continue
        key = (r.failure_stage or "").strip() or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _count_by_stage_kind(results: list[AttemptResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in results:
        if r.phase != "measured" or r.pass_:
            continue
        stage = (r.failure_stage or "").strip() or "unknown"
        kind = (r.failure_kind or "").strip() or "unknown"
        key = f"{stage}:{kind}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _count_failure_notes(results: list[AttemptResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in results:
        if r.phase != "measured" or r.pass_:
            continue
        note = (r.failure_note or "").strip()
        if not note:
            continue
        counts[note] = counts.get(note, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _sum_counter(results: list[AttemptResult], key: str) -> int:
    total = 0
    for r in results:
        if r.phase != "measured":
            continue
        total += int(r.counters.get(key, 0) or 0)
    return total


def _render_report(
    *,
    board: str,
    config_path: str,
    target_success_rate: float,
    sleep_seconds: float,
    results: list[AttemptResult],
    artifact_dir: Path,
    spread: str,
    min_measured_runs_for_go: int,
    go_by_ci_lower_bound: bool,
) -> str:
    measured = [r for r in results if r.phase == "measured"]
    warmup = [r for r in results if r.phase == "warmup"]
    successes = sum(1 for r in measured if r.pass_)
    total = len(measured)
    success_rate = (successes / total) if total else 0.0

    by_reason = _count_by_reason(results)
    by_stage = _count_by_stage(results)
    by_stage_kind = _count_by_stage_kind(results)
    by_note = _count_failure_notes(results)
    example_success = next((r for r in measured if r.pass_), None)
    example_failure = next((r for r in measured if not r.pass_), None)

    ci_low, ci_high = _wilson_interval(successes, total) if total else (0.0, 0.0)
    durations = []
    for r in measured:
        d = r.metrics_duration_seconds if r.metrics_duration_seconds is not None else r.duration_seconds
        durations.append(float(d))
    dur_p50 = _median(durations)
    dur_p95 = _percentile(durations, 95.0)

    flags = [bool(r.pass_) for r in measured]
    longest_success_streak = _longest_streak(flags, value=True) if flags else 0
    longest_failure_streak = _longest_streak(flags, value=False) if flags else 0

    latency_p50_threshold_s = 180.0
    latency_p95_threshold_s = 420.0
    latency_ok = True
    if dur_p50 is not None and dur_p95 is not None:
        latency_ok = (dur_p50 <= latency_p50_threshold_s) and (dur_p95 <= latency_p95_threshold_s)

    stability_ok = longest_failure_streak < 3

    meets_min_runs = total >= int(min_measured_runs_for_go or 0)
    threshold_basis = ci_low if go_by_ci_lower_bound else success_rate
    decision = "CONDITIONAL"
    if meets_min_runs:
        decision = "GO" if (threshold_basis >= target_success_rate and stability_ok and latency_ok) else "NO-GO"

    lines: list[str] = []
    lines.append(f"# {board.title()} Viability Report")
    lines.append("")
    lines.append(f"**Generated:** {_utc_now().strftime('%Y-%m-%d %H:%M UTC')}  ")
    lines.append(f"**Board:** `{board}`  ")
    lines.append(f"**Config:** `{config_path}`  ")
    lines.append(f"**Warmup Runs:** {len(warmup)}  ")
    lines.append(f"**Measured Runs:** {len(measured)}  ")
    lines.append(f"**Spread:** `{spread}`  ")
    lines.append(f"**Sleep Between Runs:** {sleep_seconds:.0f}s (base)  ")
    lines.append(f"**Target Success Rate:** {_pct(target_success_rate)}  ")
    lines.append(f"**Success Rate (95% CI, Wilson):** {_pct(success_rate)} (CI: {_pct(ci_low)} - {_pct(ci_high)})  ")
    lines.append(f"**Artifact Dir:** `{artifact_dir}`")
    lines.append("")
    lines.append("## Viability Criteria (Defaults)")
    lines.append("")
    lines.append(f"- Minimum measured runs for decision: **{int(min_measured_runs_for_go)}**")
    lines.append(
        f"- GO threshold: **{_pct(target_success_rate)}** (basis: {'CI lower bound' if go_by_ci_lower_bound else 'point estimate'})"
    )
    lines.append("- Stability gate: longest consecutive-failure streak **< 3**")
    lines.append(f"- Latency gate: p50 ≤ **{latency_p50_threshold_s:.0f}s**, p95 ≤ **{latency_p95_threshold_s:.0f}s**")
    lines.append("- Cost gate: report `capsolver_solved` count; multiply by your solver $/solve to estimate $/successful run")
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append(f"- Successes: **{successes}/{total}** (**{_pct(success_rate)}**) (pass = `jobs_unique_collected >= 1`)")
    if dur_p50 is not None:
        lines.append(f"- Duration p50: **{dur_p50:.1f}s**")
    if dur_p95 is not None:
        lines.append(f"- Duration p95: **{dur_p95:.1f}s**")
    if flags:
        lines.append(f"- Longest success streak: **{longest_success_streak}**")
        lines.append(f"- Longest failure streak: **{longest_failure_streak}**")
    lines.append(f"- Captcha encounters (sum): **{_sum_counter(results, 'captcha_encounters')}**")
    lines.append(f"- Blocked pages (sum): **{_sum_counter(results, 'blocked_pages')}**")
    lines.append(f"- CapSolver solved (sum): **{_sum_counter(results, 'capsolver_solved')}**")
    lines.append(f"- Solver failures (sum): **{_sum_counter(results, 'solver_failures')}**")
    lines.append("")
    lines.append("## Attempts (Measured)")
    lines.append("")
    lines.append(
        "| Run | Pass | jobs_unique_collected | failure_stage | failure_kind | duration_s | captcha_encounters | blocked_pages | capsolver_solved | solver_failures | exit_code | run_metrics |"
    )
    lines.append("|---:|:---:|---:|---|---|---:|---:|---:|---:|---:|---:|---|")
    for r in measured:
        counters = r.counters or {}
        d = r.metrics_duration_seconds if r.metrics_duration_seconds is not None else r.duration_seconds
        lines.append(
            "| {run} | {pass_} | {jobs} | {stage} | {kind} | {dur:.1f} | {captcha} | {blocked} | {capsolver} | {fails} | {exit_code} | {metrics} |".format(
                run=r.run_index,
                pass_="✅" if r.pass_ else "❌",
                jobs=r.jobs_unique_collected,
                stage=(r.failure_stage or "") if not r.pass_ else "",
                kind=(r.failure_kind or r.failure_reason or "") if not r.pass_ else "",
                dur=float(d),
                captcha=int(counters.get("captcha_encounters") or 0),
                blocked=int(counters.get("blocked_pages") or 0),
                capsolver=int(counters.get("capsolver_solved") or 0),
                fails=int(counters.get("solver_failures") or 0),
                exit_code=r.exit_code,
                metrics=f"`{r.run_metrics_path}`" if r.run_metrics_path else "(missing)",
            )
        )
    lines.append("")
    lines.append("## Failure Breakdown")
    lines.append("")
    if not by_reason:
        lines.append("- (none)")
    else:
        for reason, count in by_reason.items():
            lines.append(f"- {reason}: {count}")
    lines.append("")
    lines.append("## Failure Breakdown (Stage)")
    lines.append("")
    if not by_stage:
        lines.append("- (none)")
    else:
        for stage, count in by_stage.items():
            lines.append(f"- {stage}: {count}")
    lines.append("")
    lines.append("## Failure Breakdown (Stage:Kind)")
    lines.append("")
    if not by_stage_kind:
        lines.append("- (none)")
    else:
        for k, count in by_stage_kind.items():
            lines.append(f"- {k}: {count}")
    lines.append("")
    lines.append("## Failure Notes (Best-Effort)")
    lines.append("")
    if not by_note:
        lines.append("- (none)")
    else:
        for note, count in by_note.items():
            lines.append(f"- {note}: {count}")
    lines.append("")
    lines.append("## Example Artifacts")
    lines.append("")
    if example_success:
        lines.append(f"- Success stdout: `{example_success.stdout_path}`")
        if example_success.run_metrics_path:
            lines.append(f"- Success metrics: `{example_success.run_metrics_path}`")
    if example_failure:
        lines.append(f"- Failure stdout: `{example_failure.stdout_path}`")
        if example_failure.run_metrics_path:
            lines.append(f"- Failure metrics: `{example_failure.run_metrics_path}`")
        if example_failure.failure_note:
            lines.append(f"- Failure note: {example_failure.failure_note}")
    if not example_success and not example_failure:
        lines.append("- (no attempts recorded)")
    lines.append("")
    lines.append("## Decision")
    lines.append("")
    lines.append(f"**{decision}**")
    lines.append("")
    if not meets_min_runs:
        lines.append(
            f"Decision is CONDITIONAL because measured runs ({total}) < minimum ({int(min_measured_runs_for_go)})."
        )
    else:
        basis_text = f"CI lower bound ({_pct(ci_low)})" if go_by_ci_lower_bound else f"point estimate ({_pct(success_rate)})"
        lines.append(f"Basis: {basis_text} vs threshold {_pct(target_success_rate)}.")
        lines.append(f"Criteria: stability={'PASS' if stability_ok else 'FAIL'}, latency={'PASS' if latency_ok else 'FAIL'}.")
    lines.append("")
    lines.append("### What Would Change This Decision")
    lines.append("")
    if decision != "GO":
        lines.append("- Increase sample size to 50 measured runs (preferably time-spread) and re-evaluate CI.")
        lines.append("- If failures are mostly `timeout`: test with lower-latency proxies and consider timeout tuning (navigation/page).")
        lines.append("- If failures are mostly `selector`: re-run recon and update selectors for results cards/details.")
        lines.append("- If failures are mostly `challenge`: treat as not production-viable; prefer alternate sources or reduce automation surface area.")
    else:
        lines.append("- Keep weekly benchmark cadence; re-run after proxy pool/provider changes or collector selector changes.")
    lines.append("")
    return "\n".join(lines)


def _run_once(
    *,
    run_index: int,
    phase: str,
    board: str,
    config_path: str,
    artifact_dir: Path,
) -> AttemptResult:
    import subprocess

    started = time.monotonic()
    started_at = _utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")

    stdout_path = artifact_dir / f"{phase}_run_{run_index:02d}.stdout.log"
    board_dir = REPO_ROOT / "boards" / board

    before_latest = _find_latest_run_metrics(board_dir)
    before_latest_path = str(before_latest) if before_latest else None
    before_latest_mtime = before_latest.stat().st_mtime if before_latest and before_latest.exists() else 0.0

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")

    cmd = [str(REPO_ROOT / "scripts" / "run_board.sh"), board, config_path]
    with stdout_path.open("w", encoding="utf-8") as fp:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            env=env,
            stdout=fp,
            stderr=subprocess.STDOUT,
            text=True,
        )

    duration = max(time.monotonic() - started, 0.0)

    metrics_path = None
    latest = _find_latest_run_metrics(board_dir)
    if latest and latest.exists():
        latest_mtime = latest.stat().st_mtime
        latest_path = str(latest)
        if latest_path != before_latest_path or latest_mtime > before_latest_mtime:
            metrics_path = latest

    counters: dict[str, int] = {}
    jobs_unique = 0
    pass_ = False
    failure_reason: Optional[str] = None
    metrics_duration_seconds: Optional[float] = None
    timings_ms: dict[str, int] = {}
    result: Optional[str] = None
    failure_stage: Optional[str] = None
    failure_kind: Optional[str] = None
    exception_class: Optional[str] = None
    exception_message: Optional[str] = None
    last_url: Optional[str] = None

    if metrics_path is None:
        failure_reason = "metrics_missing"
        failure_kind = "metrics_missing"
    else:
        payload = _read_json(metrics_path)
        counters = dict(payload.get("counters") or {})
        gauges = payload.get("gauges") or {}
        try:
            if payload.get("duration_seconds") is not None:
                metrics_duration_seconds = float(payload.get("duration_seconds"))
        except Exception:
            metrics_duration_seconds = None

        extra = payload.get("extra") or {}
        if isinstance(extra, dict):
            result = str(extra.get("result") or "") or None
            failure_stage = str(extra.get("failure_stage") or "") or None
            failure_kind = str(extra.get("failure_kind") or "") or None
            exception_class = str(extra.get("exception_class") or "") or None
            exception_message = str(extra.get("exception_message") or "") or None
            last_url = str(extra.get("last_url") or "") or None
            tm = extra.get("timings_ms")
            if isinstance(tm, dict):
                for k, v in tm.items():
                    try:
                        timings_ms[str(k)] = int(v)
                    except Exception:
                        continue
        try:
            jobs_unique = int(gauges.get("jobs_unique_collected") or 0)
        except Exception:
            jobs_unique = 0
        pass_ = jobs_unique >= 1

        if not pass_:
            if int(counters.get("captcha_encounters") or 0) > 0 or int(counters.get("blocked_pages") or 0) > 0:
                failure_reason = "blocked_by_captcha"
                failure_kind = failure_kind or "challenge"
            else:
                failure_reason = "no_jobs_collected"
                failure_kind = failure_kind or "no_jobs_collected"

    if proc.returncode != 0 and not pass_:
        failure_reason = failure_reason or "board_error"
        failure_kind = failure_kind or "board_error"

    failure_note = None if pass_ else _infer_failure_note(stdout_path)

    return AttemptResult(
        run_index=run_index,
        phase=phase,
        started_at_utc=started_at,
        duration_seconds=round(duration, 3),
        metrics_duration_seconds=round(metrics_duration_seconds, 6) if metrics_duration_seconds is not None else None,
        exit_code=int(proc.returncode),
        stdout_path=str(stdout_path),
        run_metrics_path=str(metrics_path) if metrics_path else None,
        pass_=bool(pass_),
        jobs_unique_collected=int(jobs_unique),
        counters={k: int(v) for k, v in counters.items() if isinstance(v, (int, float, str))},
        timings_ms=timings_ms,
        result=result,
        failure_stage=failure_stage,
        failure_kind=failure_kind,
        exception_class=exception_class,
        exception_message=exception_message,
        last_url=last_url,
        failure_reason=failure_reason,
        failure_note=failure_note,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Reliability benchmark runner for board collectors.")
    p.add_argument("--board", required=True, help="Board name (e.g. glassdoor)")
    p.add_argument("--config", required=True, help="Config path (repo-root-relative or absolute)")
    p.add_argument("--measured-runs", type=int, default=None, help="Number of measured runs")
    p.add_argument("--runs", type=int, default=None, help="(deprecated) alias for --measured-runs")
    p.add_argument("--warmup-runs", type=int, default=1, help="Number of warmup runs (not counted)")
    p.add_argument("--sleep-seconds", type=float, default=45.0, help="Sleep between runs (seconds)")
    p.add_argument("--target-success-rate", type=float, default=0.80, help="Threshold for keep vs switch recommendation")
    p.add_argument("--extend-runs", type=int, default=10, help="Additional measured runs if below target after initial runs")
    p.add_argument("--no-extend", action="store_true", help="Disable automatic run extension below target")
    p.add_argument("--spread", default="immediate", help="Run spacing mode: immediate | hourly:N | daily:N")
    p.add_argument("--min-measured-runs-for-go", type=int, default=20, help="Minimum measured runs before GO/NO-GO")
    p.add_argument("--go-by-point-estimate", action="store_true", help="Use point estimate instead of CI lower bound")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    board = (args.board or "").strip()
    if not board:
        print("ERROR: --board is required", file=sys.stderr)
        return 2

    config_arg = (args.config or "").strip()
    if not config_arg:
        print("ERROR: --config is required", file=sys.stderr)
        return 2

    config_path = Path(config_arg)
    if not config_path.is_absolute():
        config_path = REPO_ROOT / config_path
    if not config_path.exists():
        print(f"ERROR: config not found: {config_path}", file=sys.stderr)
        return 2

    board_dir = REPO_ROOT / "boards" / board
    if not board_dir.exists():
        print(f"ERROR: board not found: {board_dir}", file=sys.stderr)
        return 2

    measured_runs = args.measured_runs if args.measured_runs is not None else (args.runs if args.runs is not None else 10)
    measured_runs = int(measured_runs or 0)

    spread = str(args.spread or "immediate").strip().lower()
    spread_spacing_seconds: Optional[float] = None
    if spread and spread != "immediate":
        if spread.startswith("hourly"):
            spread_spacing_seconds = 3600.0
        elif spread.startswith("daily"):
            spread_spacing_seconds = 8 * 3600.0
        if ":" in spread:
            try:
                _, n_raw = spread.split(":", 1)
                n = int(n_raw.strip())
                if args.measured_runs is None and args.runs is None:
                    measured_runs = n
            except Exception:
                pass

    run_slug = _utc_now_slug()
    artifact_dir = REPO_ROOT / "docs" / "reliability" / "artifacts" / board / f"benchmark_{run_slug}"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    results: list[AttemptResult] = []

    for i in range(1, int(args.warmup_runs or 0) + 1):
        r = _run_once(
            run_index=i,
            phase="warmup",
            board=board,
            config_path=str(config_path),
            artifact_dir=artifact_dir,
        )
        results.append(r)
        if args.sleep_seconds and args.sleep_seconds > 0:
            time.sleep(float(args.sleep_seconds))

    for i in range(1, measured_runs + 1):
        run_started = time.monotonic()
        r = _run_once(
            run_index=i,
            phase="measured",
            board=board,
            config_path=str(config_path),
            artifact_dir=artifact_dir,
        )
        results.append(r)
        if i != measured_runs:
            if spread_spacing_seconds:
                elapsed = max(time.monotonic() - run_started, 0.0)
                remaining = max(spread_spacing_seconds - elapsed, 0.0)
                if remaining > 0:
                    time.sleep(remaining)
            elif args.sleep_seconds and args.sleep_seconds > 0:
                time.sleep(float(args.sleep_seconds))

    if not args.no_extend and measured_runs > 0:
        measured = [r for r in results if r.phase == "measured"]
        successes = sum(1 for r in measured if r.pass_)
        rate = (successes / len(measured)) if measured else 0.0
        if len(measured) == measured_runs and measured_runs >= 10 and rate < float(args.target_success_rate):
            extra = int(args.extend_runs or 0)
            for i in range(measured_runs + 1, measured_runs + extra + 1):
                r = _run_once(
                    run_index=i,
                    phase="measured",
                    board=board,
                    config_path=str(config_path),
                    artifact_dir=artifact_dir,
                )
                results.append(r)
                if args.sleep_seconds and args.sleep_seconds > 0 and i != (measured_runs + extra):
                    time.sleep(float(args.sleep_seconds))

    raw_path = artifact_dir / "results.json"
    raw_path.write_text(
        json.dumps([r.__dict__ for r in results], indent=2, sort_keys=True),
        encoding="utf-8",
    )

    report = _render_report(
        board=board,
        config_path=str(config_path),
        target_success_rate=float(args.target_success_rate),
        sleep_seconds=float(args.sleep_seconds),
        results=results,
        artifact_dir=artifact_dir,
        spread=spread,
        min_measured_runs_for_go=int(args.min_measured_runs_for_go or 0),
        go_by_ci_lower_bound=not bool(args.go_by_point_estimate),
    )

    measured = [r for r in results if r.phase == "measured"]
    successes = sum(1 for r in measured if r.pass_)
    total = len(measured)
    rate = (successes / total) if total else 0.0
    ci_low, ci_high = _wilson_interval(successes, total) if total else (0.0, 0.0)

    docs_dir = REPO_ROOT / "docs" / "reliability"
    docs_dir.mkdir(parents=True, exist_ok=True)
    report_path = docs_dir / f"{board}.md"
    viability_report_path = docs_dir / f"{board}_viability.md"
    report_path.write_text(report, encoding="utf-8")
    viability_report_path.write_text(report, encoding="utf-8")

    durations = []
    for r in measured:
        d = r.metrics_duration_seconds if r.metrics_duration_seconds is not None else r.duration_seconds
        durations.append(float(d))

    summary = {
        "generated_utc": _utc_now().strftime("%Y-%m-%d %H:%M UTC"),
        "board": board,
        "config": str(config_path),
        "warmup_runs": int(args.warmup_runs or 0),
        "measured_runs": total,
        "successes": successes,
        "success_rate": rate,
        "success_rate_ci_wilson_95": {"low": ci_low, "high": ci_high},
        "duration_seconds": {
            "p50": _median(durations),
            "p95": _percentile(durations, 95.0),
        },
        "streaks": {
            "longest_success": _longest_streak([bool(r.pass_) for r in measured], value=True) if measured else 0,
            "longest_failure": _longest_streak([bool(r.pass_) for r in measured], value=False) if measured else 0,
        },
        "failure_kind_counts": _count_by_reason(results),
        "failure_stage_counts": _count_by_stage(results),
        "failure_stage_kind_counts": _count_by_stage_kind(results),
        "counters_sum": {
            "captcha_encounters": _sum_counter(results, "captcha_encounters"),
            "blocked_pages": _sum_counter(results, "blocked_pages"),
            "capsolver_solved": _sum_counter(results, "capsolver_solved"),
            "solver_failures": _sum_counter(results, "solver_failures"),
        },
        "artifact_dir": str(artifact_dir),
        "raw_results_json": str(raw_path),
        "viability_report_md": str(viability_report_path),
    }

    summary_path = docs_dir / "artifacts" / f"{board}_viability_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    print(f"Wrote report: {report_path}")
    print(f"Wrote viability report: {viability_report_path}")
    print(f"Wrote raw results: {raw_path}")
    print(f"Wrote summary: {summary_path}")
    print(f"Measured success rate: {_pct(rate)} ({successes}/{total}) (CI: {_pct(ci_low)} - {_pct(ci_high)})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
