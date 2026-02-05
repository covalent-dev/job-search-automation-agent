#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
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
    exit_code: int
    stdout_path: str
    run_metrics_path: Optional[str]
    pass_: bool
    jobs_unique_collected: int
    counters: dict[str, int]
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
        key = r.failure_reason or ("pass" if r.pass_ else "unknown")
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
) -> str:
    measured = [r for r in results if r.phase == "measured"]
    warmup = [r for r in results if r.phase == "warmup"]
    successes = sum(1 for r in measured if r.pass_)
    total = len(measured)
    success_rate = (successes / total) if total else 0.0

    by_reason = _count_by_reason(results)
    by_note = _count_failure_notes(results)
    example_success = next((r for r in measured if r.pass_), None)
    example_failure = next((r for r in measured if not r.pass_), None)

    recommendation = "KEEP provider" if success_rate >= target_success_rate else "SWITCH provider"

    lines: list[str] = []
    lines.append(f"# {board.title()} Reliability Benchmark")
    lines.append("")
    lines.append(f"**Generated:** {_utc_now().strftime('%Y-%m-%d %H:%M UTC')}  ")
    lines.append(f"**Board:** `{board}`  ")
    lines.append(f"**Config:** `{config_path}`  ")
    lines.append(f"**Warmup Runs:** {len(warmup)}  ")
    lines.append(f"**Measured Runs:** {len(measured)}  ")
    lines.append(f"**Sleep Between Runs:** {sleep_seconds:.0f}s  ")
    lines.append(f"**Target Success Rate:** {_pct(target_success_rate)}  ")
    lines.append(f"**Artifact Dir:** `{artifact_dir}`")
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append(f"- Successes: **{successes}/{total}** (**{_pct(success_rate)}**) (pass = `jobs_unique_collected >= 1`)")
    lines.append(f"- Captcha encounters (sum): **{_sum_counter(results, 'captcha_encounters')}**")
    lines.append(f"- Blocked pages (sum): **{_sum_counter(results, 'blocked_pages')}**")
    lines.append(f"- CapSolver solved (sum): **{_sum_counter(results, 'capsolver_solved')}**")
    lines.append(f"- Solver failures (sum): **{_sum_counter(results, 'solver_failures')}**")
    lines.append("")
    lines.append("## Attempts (Measured)")
    lines.append("")
    lines.append(
        "| Run | Pass | jobs_unique_collected | captcha_encounters | blocked_pages | capsolver_solved | solver_failures | exit_code | run_metrics |"
    )
    lines.append("|---:|:---:|---:|---:|---:|---:|---:|---:|---|")
    for r in measured:
        counters = r.counters or {}
        lines.append(
            "| {run} | {pass_} | {jobs} | {captcha} | {blocked} | {capsolver} | {fails} | {exit_code} | {metrics} |".format(
                run=r.run_index,
                pass_="✅" if r.pass_ else "❌",
                jobs=r.jobs_unique_collected,
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
    lines.append("## Recommendation")
    lines.append("")
    lines.append(f"**{recommendation}** (threshold: {_pct(target_success_rate)})")
    lines.append("")
    if recommendation.startswith("SWITCH"):
        lines.append(
            "Next step: switch to cleaner residential/ISP IPs with lower latency and stable sticky sessions; re-run this benchmark."
        )
    else:
        lines.append(
            "Next step: keep provider and monitor weekly; re-run this benchmark after any proxy pool/provider changes."
        )
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

    if metrics_path is None:
        failure_reason = "metrics_missing"
    else:
        payload = _read_json(metrics_path)
        counters = dict(payload.get("counters") or {})
        gauges = payload.get("gauges") or {}
        try:
            jobs_unique = int(gauges.get("jobs_unique_collected") or 0)
        except Exception:
            jobs_unique = 0
        pass_ = jobs_unique >= 1

        if not pass_:
            if int(counters.get("captcha_encounters") or 0) > 0 or int(counters.get("blocked_pages") or 0) > 0:
                failure_reason = "blocked_by_captcha"
            else:
                failure_reason = "no_jobs_collected"

    if proc.returncode != 0 and not pass_:
        failure_reason = failure_reason or "board_error"

    failure_note = None if pass_ else _infer_failure_note(stdout_path)

    return AttemptResult(
        run_index=run_index,
        phase=phase,
        started_at_utc=started_at,
        duration_seconds=round(duration, 3),
        exit_code=int(proc.returncode),
        stdout_path=str(stdout_path),
        run_metrics_path=str(metrics_path) if metrics_path else None,
        pass_=bool(pass_),
        jobs_unique_collected=int(jobs_unique),
        counters={k: int(v) for k, v in counters.items() if isinstance(v, (int, float, str))},
        failure_reason=failure_reason,
        failure_note=failure_note,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Reliability benchmark runner for board collectors.")
    p.add_argument("--board", required=True, help="Board name (e.g. glassdoor)")
    p.add_argument("--config", required=True, help="Config path (repo-root-relative or absolute)")
    p.add_argument("--runs", type=int, default=10, help="Number of measured runs")
    p.add_argument("--warmup-runs", type=int, default=1, help="Number of warmup runs (not counted)")
    p.add_argument("--sleep-seconds", type=float, default=45.0, help="Sleep between runs (seconds)")
    p.add_argument("--target-success-rate", type=float, default=0.80, help="Threshold for keep vs switch recommendation")
    p.add_argument("--extend-runs", type=int, default=10, help="Additional measured runs if below target after initial runs")
    p.add_argument("--no-extend", action="store_true", help="Disable automatic run extension below target")
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

    measured_runs = int(args.runs or 0)
    for i in range(1, measured_runs + 1):
        r = _run_once(
            run_index=i,
            phase="measured",
            board=board,
            config_path=str(config_path),
            artifact_dir=artifact_dir,
        )
        results.append(r)
        if args.sleep_seconds and args.sleep_seconds > 0 and i != measured_runs:
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
    )

    report_path = REPO_ROOT / "docs" / "reliability" / f"{board}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    measured = [r for r in results if r.phase == "measured"]
    successes = sum(1 for r in measured if r.pass_)
    rate = (successes / len(measured)) if measured else 0.0
    print(f"Wrote report: {report_path}")
    print(f"Wrote raw results: {raw_path}")
    print(f"Measured success rate: {_pct(rate)} ({successes}/{len(measured)})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
