"""

Configuration loader for Job Bot
Reads and validates settings.yaml
"""

import yaml
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Loads and validates configuration from YAML file"""
    
    def __init__(self, config_path: str = "config/settings.yaml"):
        self.config_path = Path(config_path)
        self.config: Dict[str, Any] = {}
        self._load()
    
    def _load(self) -> None:
        """Load config from YAML file"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        
        try:
            with open(self.config_path, 'r') as f:
                self.config = yaml.safe_load(f)
            logger.info(f"✓ Config loaded from {self.config_path}")
        except yaml.YAMLError as e:
            logger.error(f"Error parsing config file: {e}")
            raise
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get config value by dot notation (e.g., 'search.keywords')"""
        keys = key.split('.')
        value = self.config
        
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k, default)
            else:
                return default
        
        return value
    
    # === Search Config ===
    
    def get_keywords(self) -> List[str]:
        """Get list of job search keywords"""
        return self.get('search.keywords', [])
    
    def get_location(self) -> str:
        """Get job search location"""
        return self.get('search.location', 'Remote')
    
    def get_max_results(self) -> int:
        """Get max results per search"""
        return self.get('search.max_results_per_search', 50)
    
    def get_job_boards(self) -> List[str]:
        """Get list of job boards to search"""
        return self.get('search.job_boards', ['Indeed'])
    
    # === Output Config ===
    
    def get_output_path(self, file_type: str = 'json') -> Path:
        """Get output file path with timestamp if enabled"""
        use_timestamp = self.get('output.use_timestamp', True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S') if use_timestamp else ''
        
        template = self.get(f'output.{file_type}_file', f'output/jobs.{file_type}')
        filename = template.replace('{timestamp}', timestamp)
        
        return Path(filename)
    
    # === Browser Config ===

    def is_headless(self) -> bool:
        """Check if browser should run in headless mode"""
        return self.get('browser.headless', False)

    def get_min_delay(self) -> float:
        """Get minimum delay between actions"""
        return float(self.get('browser.min_delay', 0.5))

    def get_max_delay(self) -> float:
        """Get maximum delay between actions"""
        return float(self.get('browser.max_delay', 2.0))

    def get_page_timeout(self) -> int:
        """Get page load timeout in milliseconds"""
        return self.get('browser.page_timeout', 30) * 1000
    
    # === AI Config ===
    
    def is_ai_enabled(self) -> bool:
        """Check if AI filtering is enabled"""
        return self.get('ai_filter.enabled', False)
    
    def get_ai_model(self) -> str:
        """Get AI model name"""
        return self.get('ai_filter.model', 'deepseek-coder-v2:latest')
    
    def get_ai_prompt(self) -> str:
        """Get AI scoring prompt template"""
        return self.get('ai_filter.scoring_prompt', '')
    
    # === Logging Config ===
    
    def get_log_level(self) -> str:
        """Get logging level"""
        return self.get('logging.level', 'INFO')
    
    def get_log_file(self) -> Path:
        """Get log file path with timestamp"""
        template = self.get('logging.log_file', 'logs/job_bot.log')
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = template.replace('{timestamp}', timestamp)
        return Path(filename)
    
    def __repr__(self) -> str:
        keywords = self.get_keywords()
        location = self.get_location()
        return f"<Config: {len(keywords)} keywords, location={location}>"


# Convenience function
def load_config(config_path: str = "config/settings.yaml") -> ConfigLoader:
    """Load configuration from file"""
    return ConfigLoader(config_path)
