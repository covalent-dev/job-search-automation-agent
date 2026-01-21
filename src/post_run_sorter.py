"""
Post-run sorter: rule-based filter + optional AI scoring on saved JSON.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

from ai_scorer import AIScorer
from config_loader import ConfigLoader
from models import Job, SearchQuery, SearchResults

logger = logging.getLogger(__name__)


def _load_results(path: Path) -> SearchResults:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "jobs" in payload:
        return SearchResults.model_validate(payload)
    if isinstance(payload, list):
        return SearchResults(queries=[], jobs=[Job.model_validate(j) for j in payload], total_jobs=len(payload))
    raise ValueError("Unsupported JSON format: expected SearchResults or list of jobs")


def _normalize_keywords(values: Iterable[str]) -> List[str]:
    return [v.strip().lower() for v in values if v and v.strip()]


def _match_any(text: str, keywords: List[str]) -> bool:
    if not keywords:
        return True
    lower = text.lower()
    for kw in keywords:
        if len(kw) <= 2:
            if re.search(rf"\\b{re.escape(kw)}\\b", lower):
                return True
            continue
        if kw in lower:
            return True
    return False


def _should_exclude(text: str, exclude_keywords: List[str]) -> bool:
    if not exclude_keywords:
        return False
    lower = text.lower()
    return any(kw in lower for kw in exclude_keywords)


def _build_index_text(job: Job) -> str:
    parts = [job.title, job.company, job.location, job.description or ""]
    return " ".join(p for p in parts if p)


def _find_latest_output_json(output_dir: Path) -> Optional[Path]:
    candidates = sorted(output_dir.glob("jobs_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _format_board_label(config: ConfigLoader) -> str:
    boards = config.get_job_boards()
    primary = boards[0] if boards else "jobs"
    return primary.replace("-", " ").replace("_", " ").title()


def _write_outputs(config: ConfigLoader, jobs: List[Job], queries: List[SearchQuery], summary: dict) -> dict:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / f"scored_jobs_{timestamp}.json"
    md_path = output_dir / f"scored_jobs_{timestamp}.md"

    results = SearchResults(queries=queries, jobs=jobs, total_jobs=len(jobs))
    json_path.write_text(json.dumps(results.model_dump(), indent=2, default=str), encoding="utf-8")

    board_label = _format_board_label(config)
    pretty_time = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"# {board_label} Scored Jobs — {pretty_time}\n",
        f"**Total Jobs:** {len(jobs)}  ",
        f"**Generated:** {pretty_time}\n",
        "## Filter Summary\n",
        f"- Input jobs: {summary['input_total']}",
        f"- Filtered out: {summary['filtered_out']}",
        f"- AI scored: {summary['ai_scored']}\n",
        "---\n",
        "## Ranked Listings\n",
    ]

    for i, job in enumerate(jobs, 1):
        lines.append(f"### {i}. {job.title}\n")
        lines.append(f"**Company:** {job.company}  ")
        lines.append(f"**Location:** {job.location}  ")
        lines.append(f"**Source:** {job.source}  ")
        if job.salary:
            lines.append(f"**Salary:** {job.salary}  ")
        if job.date_posted:
            lines.append(f"**Posted:** {job.date_posted}  ")
        if job.ai_score is not None:
            lines.append(f"**AI Score:** {job.ai_score}/10  ")
        lines.append(f"\n**Link:** [{job.title}]({job.link})\n")
        if job.description:
            lines.append(f"> {job.description[:300]}{'...' if len(job.description) > 300 else ''}\n")
        if job.ai_reasoning:
            reasoning = job.ai_reasoning[:180]
            suffix = "..." if len(job.ai_reasoning) > 180 else ""
            lines.append(f"**AI Notes:** {reasoning}{suffix}\n")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")

    # Vault sync
    if config.is_vault_sync_enabled() and config.get_vault_path():
        vault_path = config.get_vault_path()
        vault_path.mkdir(parents=True, exist_ok=True)
        match = re.search(r"scored_jobs_(\d{8})_(\d{6})", json_path.stem)
        if match:
            date_raw, time_raw = match.groups()
            date_label = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:]}"
            time_label = time_raw[:4]
        else:
            now = datetime.now()
            date_label = now.strftime("%Y-%m-%d")
            time_label = now.strftime("%H%M")
        board_label = _format_board_label(config)
        json_dest = vault_path / f"{board_label} Scored Jobs {date_label} {time_label}.json"
        md_dest = vault_path / f"{board_label} Scored Jobs {date_label} {time_label}.md"
        json_dest.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
        md_dest.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"📁 Synced to Obsidian: {json_dest}")
        print(f"📁 Synced to Obsidian: {md_dest}")

    print(f"💾 Scored JSON saved: {json_path}")
    print(f"📝 Scored Markdown saved: {md_path}")

    return {"json": json_path, "markdown": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Post-run filter + AI scoring on saved job JSON")
    parser.add_argument("--config", default="config/settings.yaml", help="Config path")
    parser.add_argument("--input", help="Path to jobs_*.json")
    parser.add_argument("--latest", action="store_true", help="Use latest jobs_*.json in output/")
    parser.add_argument("--no-ai", action="store_true", help="Skip AI scoring")
    parser.add_argument("--min-score", type=int, default=None, help="Minimum AI score to keep")
    parser.add_argument("--top-n", type=int, default=None, help="Keep only top N scored jobs")
    parser.add_argument("--include", action="append", default=[], help="Required keyword (can repeat)")
    parser.add_argument("--exclude", action="append", default=[], help="Excluded keyword (can repeat)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    config = ConfigLoader(args.config)

    output_dir = Path("output")
    input_path = Path(args.input) if args.input else None
    if args.latest:
        input_path = _find_latest_output_json(output_dir)
    if not input_path:
        raise SystemExit("Provide --input or --latest")
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    results = _load_results(input_path)
    jobs = list(results.jobs)

    include_keywords = _normalize_keywords(args.include or config.get("post_run.include_keywords", []))
    exclude_keywords = _normalize_keywords(args.exclude or config.get("post_run.exclude_keywords", []))
    title_role_keywords = _normalize_keywords(config.get("post_run.title_role_keywords", []))
    min_score = args.min_score if args.min_score is not None else int(config.get("post_run.min_ai_score", 0))
    top_n = args.top_n if args.top_n is not None else int(config.get("post_run.top_n", 0))

    filtered = []
    filtered_out = 0
    for job in jobs:
        title = job.title or ""
        description = job.description or ""
        index_text = _build_index_text(job)

        title_match = _match_any(title, include_keywords)
        desc_match = _match_any(description, include_keywords)
        if not (title_match or desc_match):
            filtered_out += 1
            continue

        if desc_match and not title_match and title_role_keywords:
            if not _match_any(title, title_role_keywords):
                filtered_out += 1
                continue

        if _should_exclude(index_text, exclude_keywords):
            filtered_out += 1
            continue

        filtered.append(job)

    ai_scored = 0
    if not args.no_ai and config.is_ai_enabled():
        scorer = AIScorer(config)
        if scorer.available:
            scorer.score_jobs(filtered)
            ai_scored = sum(1 for job in filtered if job.ai_score is not None)
    if min_score > 0:
        filtered = [job for job in filtered if job.ai_score is not None and job.ai_score >= min_score]

    filtered.sort(key=lambda j: (j.ai_score is not None, j.ai_score or 0), reverse=True)
    if top_n and top_n > 0:
        filtered = filtered[:top_n]

    summary = {
        "input_total": len(jobs),
        "filtered_out": filtered_out,
        "ai_scored": ai_scored,
    }

    _write_outputs(config, filtered, results.queries, summary)


if __name__ == "__main__":
    main()
