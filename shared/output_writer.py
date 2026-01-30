"""
Output Writer - Exports job data to JSON and Markdown
"""

import json
import shutil
import logging
import re
from pathlib import Path
from datetime import datetime
from typing import List
from models import Job, SearchQuery, SearchResults

logger = logging.getLogger(__name__)


class OutputWriter:
    """Handles exporting job data to various formats"""

    def __init__(self, config):
        self.config = config

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
            for i, job in enumerate(jobs, 1):
                lines.append(f"### {i}. {job.title}\n")
                lines.append(f"**Company:** {job.company}  ")
                lines.append(f"**Location:** {job.location}  ")
                lines.append(f"**Source:** {job.source}  ")
                if job.salary:
                    lines.append(f"**Salary:** {job.salary}  ")
                if job.job_type and "remote" in job.location.lower():
                    lines.append(f"**Job Type:** {job.job_type}  ")
                # Show company rating for Glassdoor jobs
                if job.company_rating is not None:
                    rating_str = f"⭐ {job.company_rating:.1f}/5"
                    if job.company_review_count:
                        rating_str += f" ({job.company_review_count:,} reviews)"
                    lines.append(f"**Rating:** {rating_str}  ")
                if job.company_recommend_pct is not None:
                    lines.append(f"**Recommend:** {job.company_recommend_pct}%  ")
                # Show geo restriction for RemoteAfrica jobs
                if job.source == "remoteafrica":
                    if job.applicant_location_requirements:
                        reqs = job.applicant_location_requirements[:5]
                        extra = len(job.applicant_location_requirements) - 5
                        geo_str = ", ".join(reqs)
                        if extra > 0:
                            geo_str += f" +{extra} more"
                        lines.append(f"**Geo Restriction:** {geo_str}  ")
                    if job.job_location_type:
                        lines.append(f"**Location Type:** {job.job_location_type}  ")
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

        # Summary table
        lines.append("---\n")
        lines.append("## Summary Table\n")
        show_ai = any(job.ai_score is not None for job in jobs)
        show_rating = any(job.company_rating is not None for job in jobs)
        header = "| # | Title | Company | Location | Source | Salary | Job Type |"
        separator = "|---|-------|---------|----------|--------|--------|----------|"
        if show_rating:
            header += " Rating |"
            separator += "--------|"
        if show_ai:
            header += " AI |"
            separator += "----|"
        lines.append(header)
        lines.append(separator)
        def _escape_md(value: str) -> str:
            return value.replace("|", "\\|")

        for i, job in enumerate(jobs, 1):
            salary = job.salary if job.salary else "-"
            job_type = job.job_type if job.job_type and "remote" in job.location.lower() else "-"
            title_short = job.title[:40] + "..." if len(job.title) > 40 else job.title
            row = "| {idx} | {title} | {company} | {location} | {source} | {salary} | {job_type} |".format(
                idx=i,
                title=_escape_md(title_short),
                company=_escape_md(job.company),
                location=_escape_md(job.location),
                source=_escape_md(job.source),
                salary=_escape_md(salary),
                job_type=_escape_md(job_type),
            )
            if show_rating:
                rating = f"{job.company_rating:.1f}" if job.company_rating is not None else "-"
                row += f" {_escape_md(rating)} |"
            if show_ai:
                ai_score = f"{job.ai_score}/10" if job.ai_score is not None else "-"
                row += f" {_escape_md(ai_score)} |"
            lines.append(row)

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
