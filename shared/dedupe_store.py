"""
Dedupe Store - Cross-run job de-duplication using hash log
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import List, Tuple
from urllib.parse import parse_qs, urlparse

from models import Job

logger = logging.getLogger(__name__)


class DedupeStore:
    """Persists job hashes to skip duplicates across runs."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.seen_hashes: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return

        try:
            with open(self.path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                        job_hash = payload.get("hash")
                        if job_hash:
                            self.seen_hashes.add(job_hash)
                    except json.JSONDecodeError:
                        logger.warning("Skipping invalid dedupe line")
        except OSError as exc:
            logger.warning("Failed to read dedupe log: %s", exc)

    def filter_new(self, jobs: List[Job]) -> Tuple[List[Job], List[Job]]:
        """Return (new_jobs, duplicate_jobs) and update in-memory cache."""
        new_jobs: List[Job] = []
        duplicates: List[Job] = []

        for job in jobs:
            job_hash = self._hash_job(job)
            if job_hash in self.seen_hashes:
                duplicates.append(job)
                continue
            self.seen_hashes.add(job_hash)
            new_jobs.append(job)

        return new_jobs, duplicates

    def record(self, jobs: List[Job]) -> None:
        if not jobs:
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.path, "a") as f:
                for job in jobs:
                    payload = {
                        "hash": self._hash_job(job),
                        "link": str(job.link) if job.link else None,
                        "title": job.title,
                        "company": job.company,
                        "location": job.location,
                        "source": job.source,
                        "collected_at": job.collected_at.isoformat(),
                    }
                    f.write(json.dumps(payload) + "\n")
        except OSError as exc:
            logger.warning("Failed to write dedupe log: %s", exc)

    def _hash_job(self, job: Job) -> str:
        base = self._stable_key(job)
        return hashlib.sha256(base.encode("utf-8")).hexdigest()

    def _stable_key(self, job: Job) -> str:
        """Build a stable key that survives tracking URL changes."""
        if job.source == "indeed":
            if getattr(job, "external_id", None):
                return f"indeed|{job.external_id.strip()}"

            if job.link:
                parsed = urlparse(str(job.link))
                query = parse_qs(parsed.query)
                jk = query.get("jk", [None])[0]
                if jk:
                    return f"indeed|{jk.strip()}"

        title = (job.title or "").strip().lower()
        company = (job.company or "").strip().lower()
        location = (job.location or "").strip().lower()
        source = (job.source or "").strip().lower()
        return f"{source}|{title}|{company}|{location}"
