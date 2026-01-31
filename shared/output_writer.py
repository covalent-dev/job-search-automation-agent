"""
Output Writer - Exports job data to JSON and Markdown
"""

import json
import shutil
import logging
import re
import textwrap
from pathlib import Path
from datetime import datetime
from typing import List
from models import Job, SearchQuery, SearchResults

logger = logging.getLogger(__name__)


class OutputWriter:
    """Handles exporting job data to various formats"""

    def __init__(self, config):
        self.config = config

    def _escape_md_cell(self, value: str) -> str:
        return (value or "").replace("|", "\\|").replace("\n", " ").strip()

    def _summarize_location_cell(self, location: str, max_items: int = 8) -> str:
        """
        Make long comma-separated location lists more readable in markdown tables.

        Example:
          "AL, AZ, CA, CO, ... WI" -> "AL, AZ, CA, CO, CT, FL, GA, ID +17 more"
        """
        text = (location or "").strip()
        if "," not in text:
            return text
        parts = [p.strip() for p in text.split(",") if p and p.strip()]
        if len(parts) <= max_items:
            return text
        shown = ", ".join(parts[:max_items])
        return f"{shown} +{len(parts) - max_items} more"

    def _truncate(self, text: str, max_len: int) -> str:
        value = (text or "").strip()
        if len(value) <= max_len:
            return value
        return value[: max_len - 3].rstrip() + "..."

    def _split_ai_reasoning(self, text: str, max_bullets: int = 4) -> list[str]:
        """
        Turn AI reasoning text into short, readable bullets.
        """
        raw = (text or "").strip()
        if not raw:
            return []

        normalized = re.sub(r"\s+", " ", raw)
        sentences = re.split(r"(?<=[.!?])\s+", normalized)
        bullets: list[str] = []
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            bullets.append(self._truncate(s, 160))
            if len(bullets) >= max_bullets:
                break
        if not bullets:
            bullets = [self._truncate(normalized, 200)]
        return bullets

    def _job_details_grid_table(self, jobs: List[Job]) -> list[str]:
        show_ai = any(job.ai_score is not None for job in jobs)
        show_rating = any(job.company_rating is not None for job in jobs)

        cols = ["#", "Title", "Company", "Location", "Source", "Salary", "Job Type", "Posted"]
        if show_rating:
            cols.append("Rating")
        if show_ai:
            cols.append("AI")

        lines = [
            "| " + " | ".join(cols) + " |",
            "| " + " | ".join(["---"] * len(cols)) + " |",
        ]

        for i, job in enumerate(jobs, 1):
            title = self._truncate(job.title or "-", 80)
            title_link = f"[{self._escape_md_cell(title)}]({job.link})" if job.link else self._escape_md_cell(title)
            salary = job.salary or "-"
            job_type = job.job_type or "-"
            posted = str(job.date_posted) if job.date_posted else "-"
            rating = f"{job.company_rating:.1f}/5" if job.company_rating is not None else "-"
            ai = f"{job.ai_score}/10" if job.ai_score is not None else "-"

            row = [
                str(i),
                title_link,
                self._escape_md_cell(job.company or "Unknown Company"),
                self._escape_md_cell(self._summarize_location_cell(job.location or "-")),
                self._escape_md_cell(job.source or "-"),
                self._escape_md_cell(salary),
                self._escape_md_cell(job_type),
                self._escape_md_cell(posted),
            ]
            if show_rating:
                row.append(self._escape_md_cell(rating))
            if show_ai:
                row.append(self._escape_md_cell(ai))

            lines.append("| " + " | ".join(row) + " |")

        lines.append("")
        return lines

    def _format_board_label(self) -> str:
        boards = self.config.get_job_boards()
        primary = boards[0] if boards else "jobs"
        return primary.replace("-", " ").replace("_", " ").title()

    def _pretty_vault_name(self, source_path: Path) -> str:
        board_label = self._format_board_label()
        match = re.search(r"jobs_(\d{8})_(\d{6})", source_path.stem)
        if match:
            date_raw, time_raw = match.groups()
            date_label = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:]}"
            time_label = time_raw[:4]
        else:
            now = datetime.now()
            date_label = now.strftime("%Y-%m-%d")
            time_label = now.strftime("%H%M")
        return f"{board_label} Jobs {date_label} {time_label}{source_path.suffix}"

    def _ensure_output_dir(self, path: Path) -> None:
        """Create output directory if it doesn't exist"""
        path.parent.mkdir(parents=True, exist_ok=True)

    def write_json(self, jobs: List[Job], queries: List[SearchQuery]) -> Path:
        """Export jobs to JSON file"""
        output_path = self.config.get_output_path('json')
        self._ensure_output_dir(output_path)

        results = SearchResults(
            queries=queries,
            jobs=jobs,
            total_jobs=len(jobs)
        )

        with open(output_path, 'w') as f:
            json.dump(results.model_dump(), f, indent=2, default=str)

        logger.info(f"JSON written: {output_path}")
        print(f"💾 JSON saved: {output_path}")
        return output_path

    def write_markdown(self, jobs: List[Job], queries: List[SearchQuery]) -> Path:
        """Export jobs to Markdown file"""
        output_path = self.config.get_output_path('markdown')
        self._ensure_output_dir(output_path)

        lines = []

        # Header
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
        board_label = self._format_board_label()
        lines.append(f"# {board_label} Jobs — {timestamp}\n")
        lines.append(f"**Total Jobs:** {len(jobs)}  ")
        lines.append(f"**Generated:** {timestamp}\n")

        # Search queries
        lines.append("## Search Queries\n")
        for q in queries:
            lines.append(f"- {q.keyword} ({q.location})")
        lines.append("\n---\n")

        # Jobs by company
        lines.append("## Job Listings\n")

        if not jobs:
            lines.append("*No jobs found.*\n")
        else:
            show_ai = any(job.ai_score is not None for job in jobs)
            show_rating = any(job.company_rating is not None for job in jobs)
            for i, job in enumerate(jobs, 1):
                lines.append(f"### {i}. {job.title}\n")
                lines.append(f"**Company:** {job.company or 'Unknown Company'}  ")
                lines.append(f"**Location:** {job.location or '-'}  ")
                lines.append(f"**Source:** {job.source or '-'}  ")
                if job.salary:
                    lines.append(f"**Salary:** {job.salary}  ")
                if job.job_type:
                    lines.append(f"**Job Type:** {job.job_type}  ")
                if job.date_posted:
                    lines.append(f"**Posted:** {job.date_posted}  ")
                if show_rating and job.company_rating is not None:
                    lines.append(f"**Rating:** {job.company_rating:.1f}/5  ")
                if show_ai and job.ai_score is not None:
                    lines.append(f"**AI Score:** {job.ai_score}/10  ")

                # Extra source-specific details
                if job.source == "glassdoor":
                    if job.company_review_count:
                        lines.append(f"**Reviews:** {job.company_review_count:,}  ")
                    if job.company_recommend_pct is not None:
                        lines.append(f"**Recommend:** {job.company_recommend_pct}%  ")
                if job.source == "remoteafrica":
                    if job.applicant_location_requirements:
                        reqs = job.applicant_location_requirements[:6]
                        extra = len(job.applicant_location_requirements) - len(reqs)
                        geo_str = ", ".join(reqs)
                        if extra > 0:
                            geo_str += f" +{extra} more"
                        lines.append(f"**Geo Restriction:** {geo_str}  ")
                    if job.job_location_type:
                        lines.append(f"**Location Type:** {job.job_location_type}  ")

                lines.append(f"**Link:** [{job.title}]({job.link})\n")
                if job.description:
                    lines.append(f"> {job.description[:300]}{'...' if len(job.description) > 300 else ''}\n")
                lines.append("")

        # AI explanations between listings and the bottom grid
        if any(job.ai_reasoning for job in jobs):
            lines.append("---\n")
            lines.append("## AI Explanations\n")
            for i, job in enumerate(jobs, 1):
                if not job.ai_reasoning and job.ai_score is None:
                    continue
                title = self._truncate(job.title or "-", 90)
                score = f"{job.ai_score}/10" if job.ai_score is not None else "-"
                lines.append(f"> [!note]- {i}. {title} — {score}")
                if job.link:
                    lines.append(f"> - Link: [{title}]({job.link})")
                if job.ai_reasoning:
                    for b in self._split_ai_reasoning(job.ai_reasoning):
                        lines.append(f"> - {textwrap.fill(b, width=110)}")
                else:
                    lines.append("> - (No AI notes)")
                lines.append(">")
                lines.append("")

        # Bottom grid
        lines.append("---\n")
        lines.append("## Job Details Grid\n")
        lines.extend(self._job_details_grid_table(jobs))

        lines.append("\n---\n")
        lines.append(f"*Generated by Job Search Automation*")

        with open(output_path, 'w') as f:
            f.write('\n'.join(lines))

        logger.info(f"Markdown written: {output_path}")
        print(f"📝 Markdown saved: {output_path}")
        return output_path

    def sync_to_vault(self, files: dict) -> None:
        """Copy output files to Obsidian vault if enabled"""
        if not self.config.is_vault_sync_enabled():
            return

        vault_path = self.config.get_vault_path()
        if not vault_path:
            logger.warning("Vault sync enabled but no vault_path configured")
            return

        vault_path.mkdir(parents=True, exist_ok=True)

        for file_type, source_path in files.items():
            if source_path and source_path.exists():
                dest_path = vault_path / self._pretty_vault_name(source_path)
                shutil.copy2(source_path, dest_path)
                logger.info(f"Synced to vault: {dest_path}")
                print(f"📁 Synced to Obsidian: {dest_path}")

    def write_all(self, jobs: List[Job], queries: List[SearchQuery]) -> dict:
        """Write all output formats and sync to vault"""
        files = {
            'json': self.write_json(jobs, queries),
            'markdown': self.write_markdown(jobs, queries)
        }

        self.sync_to_vault(files)

        return files
