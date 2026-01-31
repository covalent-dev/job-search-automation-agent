#!/usr/bin/env python3

"""
Job Search Automation - Main Entry Point
Automated job search and collection system
"""

import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime
from config_loader import load_config
from models import SearchQuery, SearchResults
from collector import JobCollector
from ai_scorer import AIScorer
from dedupe_store import DedupeStore
from output_writer import OutputWriter


def setup_logging(config) -> None:
    """Configure logging for the application"""
    log_file = config.get_log_file()
    log_file.parent.mkdir(exist_ok=True)

    log_level = getattr(logging, config.get_log_level(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )

    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized: {log_file}")


def display_config(config) -> None:
    """Display loaded configuration"""
    logger = logging.getLogger(__name__)

    print("\n" + "="*60)
    print("🤖 JOB SEARCH AUTOMATION v0.1")
    print("="*60)

    print("\n📋 SEARCH PARAMETERS:")
    keywords = config.get_keywords()
    for i, keyword in enumerate(keywords, 1):
        print(f"  {i}. {keyword}")

    print(f"\n📍 Location: {config.get_location()}")
    print(f"📊 Max results per search: {config.get_max_results()}")
    max_pages = config.get_max_pages()
    max_pages_label = "unlimited (auto-stop)" if max_pages <= 0 else str(max_pages)
    print(f"📄 Max pages per search: {max_pages_label}")

    print(f"\n⚙️  BROWSER SETTINGS:")
    print(f"  Headless mode: {config.is_headless()}")
    print(f"  Delay range: {config.get_min_delay()}s - {config.get_max_delay()}s")
    print(f"  Page timeout: {config.get_page_timeout()/1000}s")
    print(f"  Detail salary fetch: {config.is_detail_salary_enabled()}")

    print(f"\n💾 OUTPUT:")
    print(f"  JSON: {config.get_output_path('json')}")
    print(f"  Markdown: {config.get_output_path('markdown')}")

    print(f"\n🤖 AI FILTER:")
    if config.is_ai_enabled():
        print(f"  ✓ Enabled")
        print(f"  Model: {config.get_ai_model()}")
    else:
        print(f"  ✗ Disabled")

    print("\n" + "="*60 + "\n")

    logger.info(f"Config validated: {len(keywords)} search queries configured")


def create_search_queries(config) -> list[SearchQuery]:
    """Create SearchQuery objects from config"""
    queries = []
    keywords = config.get_keywords()
    location = config.get_location()
    max_results = config.get_max_results()
    job_boards = config.get_job_boards()

    total = len(keywords) * len(job_boards)
    idx = 0
    for job_board in job_boards:
        for keyword in keywords:
            idx += 1
            query = SearchQuery(
                keyword=keyword,
                location=location,
                max_results=max_results,
                job_board=job_board
            )
            query.index = idx
            query.total = total
            queries.append(query)

    return queries


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Job Search Automation")
    parser.add_argument(
        "--config",
        default="config/settings.yaml",
        help="Path to config YAML",
    )
    return parser.parse_args()


def main():
    """Main execution function"""
    print("\n🚀 Starting Job Search Automation...")
    args = parse_args()

    # Load configuration
    try:
        config = load_config(args.config)
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        print("Make sure config/settings.yaml exists!")
        return 1
    except Exception as e:
        print(f"❌ Error loading config: {e}")
        return 1

    # Setup logging
    setup_logging(config)
    logger = logging.getLogger(__name__)

    # Display configuration
    display_config(config)

    # Create search queries
    queries = create_search_queries(config)
    logger.info(f"Created {len(queries)} search queries")

    print("📝 SEARCH QUERIES:")
    for i, query in enumerate(queries, 1):
        print(f"  {i}. {query}")

    # Collect jobs
    collector = JobCollector(config)
    jobs = collector.collect_all(queries)
    if collector.abort_requested:
        print("⚠️  Run aborted by user after captcha; saving collected results.")

    if not jobs:
        print("\n⚠️  No jobs collected. Check your search parameters or try again later.")
        logger.warning("No jobs collected")
        return 0

    # Cross-run dedupe
    if config.is_dedupe_enabled():
        dedupe_path = config.get_dedupe_path()
        if dedupe_path:
            store = DedupeStore(dedupe_path)
            before_count = len(jobs)
            jobs, duplicates = store.filter_new(jobs)
            store.record(jobs)
            removed = before_count - len(jobs)
            print(f"🧹 Cross-run dedupe: {removed} duplicates removed")
            logger.info("Cross-run dedupe removed %s jobs", removed)

    # AI scoring
    if config.is_ai_enabled():
        scorer = AIScorer(config)
        if scorer.available:
            print("🤖 AI scoring enabled: ranking jobs...")
            scorer.score_jobs(jobs)
        else:
            print("⚠️  AI scoring enabled but Ollama is not available; skipping scoring.")

    # Write output
    writer = OutputWriter(config)
    output_files = writer.write_all(jobs, queries)

    # Summary
    print("\n" + "="*60)
    print("✅ JOB SEARCH COMPLETE")
    print("="*60)
    print(f"\n📊 Results: {len(jobs)} jobs collected")
    print(f"📁 Files:")
    print(f"   JSON: {output_files['json']}")
    print(f"   Markdown: {output_files['markdown']}")
    print("\n" + "="*60 + "\n")

    logger.info(f"Job search complete: {len(jobs)} jobs saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
