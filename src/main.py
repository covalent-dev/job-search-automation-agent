#!/usr/bin/env python3

"""
Job Bot - Main Entry Point
Automated job search and application system
"""

import logging
from pathlib import Path
from datetime import datetime
from config_loader import load_config
from models import SearchQuery, SearchResults


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
    print("🤖 JOB BOT v0.1 - Configuration Loaded")
    print("="*60)
    
    print("\n📋 SEARCH PARAMETERS:")
    keywords = config.get_keywords()
    for i, keyword in enumerate(keywords, 1):
        print(f"  {i}. {keyword}")
    
    print(f"\n📍 Location: {config.get_location()}")
    print(f"📊 Max results per search: {config.get_max_results()}")
    print(f"🌐 Job boards: {', '.join(config.get_job_boards())}")
    
    print(f"\n⚙️  BROWSER SETTINGS:")
    print(f"  Headless mode: {config.is_headless()}")
    print(f"  Delay range: {config.get_min_delay()}s - {config.get_max_delay()}s")
    print(f"  Page timeout: {config.get_page_timeout()/1000}s")
    
    print(f"\n💾 OUTPUT:")
    print(f"  JSON: {config.get_output_path('json')}")
    print(f"  Markdown: {config.get_output_path('markdown')}")
    
    print(f"\n🤖 AI FILTER:")
    if config.is_ai_enabled():
        print(f"  ✓ Enabled")
        print(f"  Model: {config.get_ai_model()}")
    else:
        print(f"  ✗ Disabled (enable in Phase 5)")
    
    print("\n" + "="*60 + "\n")
    
    logger.info(f"Config validated: {len(keywords)} search queries configured")


def create_search_queries(config) -> list[SearchQuery]:
    """Create SearchQuery objects from config"""
    queries = []
    keywords = config.get_keywords()
    location = config.get_location()
    max_results = config.get_max_results()
    
    for keyword in keywords:
        query = SearchQuery(
            keyword=keyword,
            location=location,
            max_results=max_results,
            job_board="Indeed"
        )
        queries.append(query)
    
    return queries


def main():
    """Main execution function"""
    print("\n🚀 Starting Job Bot...")
    
    # Load configuration
    try:
        config = load_config()
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        print("Make sure config/settings.yaml exists!")
        return
    except Exception as e:
        print(f"❌ Error loading config: {e}")
        return
    
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
    
    print("\n✅ Phase 1 Complete: Foundation & Config")
    print("📦 Ready for Phase 2: Indeed Connection\n")
    
    logger.info("Phase 1 complete - configuration validated successfully")


if __name__ == "__main__":
    main()
