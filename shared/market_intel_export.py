#!/usr/bin/env python3
"""Normalize Job Bot output into the market-intel schema."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable

from models import Job, SearchResults


SKILL_TERMS = [
    "python",
    "typescript",
    "javascript",
    "react",
    "fastapi",
    "django",
    "flask",
    "sql",
    "postgres",
    "mongodb",
    "redis",
    "aws",
    "gcp",
    "azure",
    "docker",
    "kubernetes",
    "terraform",
    "ci/cd",
    "github actions",
    "rag",
    "llm",
    "langchain",
    "llamaindex",
    "openai",
    "anthropic",
    "mcp",
    "agents",
    "agentic",
    "automation",
    "workflow",
    "api integration",
    "etl",
    "mlops",
    "llmops",
    "vector database",
    "pinecone",
    "weaviate",
    "qdrant",
    "chromadb",
    "playwright",
    "selenium",
    "observability",
    "prometheus",
    "grafana",
]

DELIVERABLE_TERMS = [
    "integrate",
    "implementation",
    "deploy",
    "production",
    "automation",
    "workflow",
    "chatbot",
    "rag",
    "agent",
    "dashboard",
    "api",
    "pipeline",
    "prototype",
    "proof of concept",
    "poc",
    "migration",
    "customer",
    "client",
    "stakeholder",
]

PROOF_TERMS = [
    "portfolio",
    "github",
    "case study",
    "demo",
    "production",
    "shipped",
    "deployed",
    "open source",
    "writing sample",
    "technical assessment",
]

# Title-level seniority cues. Matched against the job TITLE only — description
# prose ("work with senior engineers") otherwise creates false positives.
SENIORITY_PATTERNS = [
    ("principal", r"\bprincipal\b"),
    ("staff", r"\bstaff\b"),
    ("senior", r"\b(senior|sr)\b"),
    ("lead", r"\blead\b"),
    ("junior", r"\b(junior|jr|entry[ -]level|new[ -]grad|associate|intern)\b"),
    ("mid", r"\b(mid[ -]level|intermediate)\b"),
]

# Section markers that begin the "nice to have / preferred / bonus" zone.
PREFERRED_MARKERS = [
    "nice to have",
    "nice-to-have",
    "nice to haves",
    "preferred qualification",
    "preferred qualifications",
    "preferred skills",
    "preferred:",
    "bonus points",
    "bonus:",
    "would be a plus",
    "good to have",
    "pluses",
]


def _compile_terms(terms: Iterable[str]) -> list[tuple[str, "re.Pattern[str]"]]:
    # Word-ish boundaries via lookarounds (not \b) so terms with internal
    # punctuation like "ci/cd" still match, while "rag" no longer hits inside
    # "storage" and "react" no longer hits inside "reactive".
    return [
        # Optional trailing "s" so plurals match ("workflows", "integrations")
        # while internal boundaries still reject substrings ("rag" in "leverage").
        (term, re.compile(rf"(?<![a-z0-9]){re.escape(term)}s?(?![a-z0-9])"))
        for term in terms
    ]


SKILL_PATTERNS = _compile_terms(SKILL_TERMS)
DELIVERABLE_PATTERNS = _compile_terms(DELIVERABLE_TERMS)
PROOF_PATTERNS = _compile_terms(PROOF_TERMS)


def split_required_preferred(description: str) -> tuple[str, str]:
    """Split a description into (required_zone, preferred_zone) at the first
    'nice to have / preferred / bonus' marker. Text before the marker is treated
    as required, text after as preferred. Returns the whole description as
    required when no marker is present."""
    lower = description.lower()
    indices = [idx for idx in (lower.find(m) for m in PREFERRED_MARKERS) if idx != -1]
    if not indices:
        return description, ""
    cut = min(indices)
    return description[:cut], description[cut:]


def load_results(path: Path) -> SearchResults:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "jobs" in payload:
        return SearchResults.model_validate(payload)
    if isinstance(payload, list):
        return SearchResults(queries=[], jobs=[Job.model_validate(item) for item in payload], total_jobs=len(payload))
    raise ValueError("Unsupported Job Bot JSON format")


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def match_terms(text: str, compiled: Iterable[tuple[str, "re.Pattern[str]"]]) -> list[str]:
    lower = text.lower()
    return sorted({term for term, pattern in compiled if pattern.search(lower)})


def infer_seniority(title: str, text: str) -> str:
    # 1) Years-of-experience requirement is the strongest signal. Use the LOWER
    #    bound of any range: "3-5 years" -> 3, "5+ years" -> 5, "2 years" -> 2.
    year_match = re.search(
        r"\b(\d{1,2})\s*(?:\+|-|–|to)?\s*(?:\d{1,2})?\s*years?\b", text.lower()
    )
    if year_match:
        years = int(year_match.group(1))
        if years >= 10:
            return "senior_out_of_reach"
        if years >= 5:
            return "senior"
        if years >= 2:
            return "mid"
        return "junior"
    # 2) Fall back to seniority cues in the TITLE only (description prose is noisy).
    title_lower = title.lower()
    for label, pattern in SENIORITY_PATTERNS:
        if re.search(pattern, title_lower):
            if label in {"principal", "staff"}:
                return "senior_out_of_reach"
            return label
    return "unspecified"


def infer_engagement_type(text: str) -> str:
    lower = text.lower()
    if any(term in lower for term in ["contract", "contractor", "freelance", "fractional"]):
        return "contract"
    if any(term in lower for term in ["full-time", "full time", "w2", "permanent"]):
        return "full_time"
    if "part-time" in lower or "part time" in lower:
        return "part_time"
    return "unspecified"


def infer_application_channel(source: str, link: str) -> str:
    host = link.lower()
    if "greenhouse.io" in host or "lever.co" in host or "workday" in host:
        return "ats"
    if source:
        return source
    return "unknown"


def normalize_job(args: argparse.Namespace, job: Job) -> dict:
    description = normalize_text(job.description_full or job.description)
    title = normalize_text(job.title)
    company = normalize_text(job.company)
    location = normalize_text(job.location)
    link = str(job.link) if job.link else ""
    index_text = " ".join([title, company, location, description])

    required_desc, preferred_desc = split_required_preferred(description)
    required_zone = " ".join([title, company, location, required_desc])
    required_skills = match_terms(required_zone, SKILL_PATTERNS)
    preferred_skills = [
        skill
        for skill in match_terms(preferred_desc, SKILL_PATTERNS)
        if skill not in required_skills
    ]

    return {
        "run_id": args.run_id,
        "track": args.track,
        "source": job.source or args.board,
        "board": args.board or job.source,
        "country": args.country,
        "country_tier": args.country_tier,
        "title": title,
        "company": company,
        "location": location,
        "posting_date": job.date_posted,
        "compensation": job.salary,
        "required_skills": required_skills,
        "preferred_skills": preferred_skills,
        "deliverable_signals": match_terms(index_text, DELIVERABLE_PATTERNS),
        "proof_signals": match_terms(index_text, PROOF_PATTERNS),
        "application_channel": infer_application_channel(job.source or args.board, link),
        "engagement_type": infer_engagement_type(index_text),
        "seniority": infer_seniority(title, index_text),
        "signal_only": args.signal_only,
        "source_quality": args.source_quality,
        "description": description,
        "link": link,
        "collected_at": job.collected_at.isoformat() if job.collected_at else None,
    }


def write_summary(path: Path, records: list[dict]) -> None:
    skill_counts = Counter(skill for record in records for skill in record["required_skills"])
    deliverable_counts = Counter(signal for record in records for signal in record["deliverable_signals"])
    seniority_counts = Counter(record["seniority"] for record in records)

    summary = {
        "total_records": len(records),
        "top_skills": skill_counts.most_common(25),
        "top_deliverable_signals": deliverable_counts.most_common(25),
        "seniority": seniority_counts.most_common(),
    }
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize Job Bot output for market-intel analysis.")
    parser.add_argument("--input", required=True, help="Path to Job Bot jobs JSON")
    parser.add_argument("--output", required=True, help="Path to normalized JSONL output")
    parser.add_argument("--summary", help="Optional summary JSON output path")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--track", choices=["A", "B"], required=True)
    parser.add_argument("--country", default="Global")
    parser.add_argument("--country-tier", default="unspecified")
    parser.add_argument("--board", default="")
    parser.add_argument("--source-quality", default="unreviewed")
    parser.add_argument("--signal-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    summary_path = Path(args.summary) if args.summary else output_path.with_suffix(".summary.json")

    results = load_results(input_path)
    records = [normalize_job(args, job) for job in results.jobs]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    write_summary(summary_path, records)

    print(f"Normalized records: {len(records)}")
    print(f"JSONL: {output_path}")
    print(f"Summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
