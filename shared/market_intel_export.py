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

SENIORITY_PATTERNS = [
    ("principal", r"\bprincipal\b"),
    ("staff", r"\bstaff\b"),
    ("senior", r"\bsenior|sr\.\b"),
    ("lead", r"\blead\b"),
    ("junior", r"\bjunior|entry[- ]level|new grad\b"),
    ("mid", r"\bmid[- ]level\b"),
]


def load_results(path: Path) -> SearchResults:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "jobs" in payload:
        return SearchResults.model_validate(payload)
    if isinstance(payload, list):
        return SearchResults(queries=[], jobs=[Job.model_validate(item) for item in payload], total_jobs=len(payload))
    raise ValueError("Unsupported Job Bot JSON format")


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def match_terms(text: str, terms: Iterable[str]) -> list[str]:
    lower = text.lower()
    matches: list[str] = []
    for term in terms:
        if term in lower:
            matches.append(term)
    return sorted(set(matches))


def infer_seniority(text: str) -> str:
    lower = text.lower()
    year_match = re.search(r"\b(1[0-5]|[2-9])\+?\s+years?\b", lower)
    if year_match:
        years = int(year_match.group(1))
        if years >= 10:
            return "senior_out_of_reach"
        if years >= 5:
            return "senior"
        if years >= 2:
            return "mid"
    for label, pattern in SENIORITY_PATTERNS:
        if re.search(pattern, lower):
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
    skills = match_terms(index_text, SKILL_TERMS)

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
        "required_skills": skills,
        "preferred_skills": [],
        "deliverable_signals": match_terms(index_text, DELIVERABLE_TERMS),
        "proof_signals": match_terms(index_text, PROOF_TERMS),
        "application_channel": infer_application_channel(job.source or args.board, link),
        "engagement_type": infer_engagement_type(index_text),
        "seniority": infer_seniority(index_text),
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
