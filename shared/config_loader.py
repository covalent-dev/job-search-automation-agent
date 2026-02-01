"""

Configuration loader for Job Bot
Reads and validates settings.yaml
Supports environment variable expansion: ${VAR} or $VAR
"""

import os
import re
import yaml
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def _load_dotenv():
    """Load .env file from project root if it exists"""
    # Walk up to find .env
    for parent in [Path.cwd()] + list(Path.cwd().parents)[:3]:
        env_file = parent / ".env"
        if env_file.exists():
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and key not in os.environ:
                            os.environ[key] = value
            logger.debug(f"Loaded env vars from {env_file}")
            return
    

def _expand_env_vars(value):
    """Expand ${VAR} or $VAR patterns in string values"""
    if not isinstance(value, str):
        return value
    pattern = r'\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)'
    def replacer(match):
        var_name = match.group(1) or match.group(2)
        return os.environ.get(var_name, "")
    return re.sub(pattern, replacer, value)


def _expand_config(config):
    """Recursively expand env vars in config dict"""
    if isinstance(config, dict):
        return {k: _expand_config(v) for k, v in config.items()}
    elif isinstance(config, list):
        return [_expand_config(v) for v in config]
    else:
        return _expand_env_vars(config)


class ConfigLoader:
    """Loads and validates configuration from YAML file"""
    
    def __init__(self, config_path: str = "config/settings.yaml"):
        self.config_path = Path(config_path)
        self.config: Dict[str, Any] = {}
        self._load()
    
    def _load(self) -> None:
        """Load config from YAML file with env var expansion"""
        # Load .env first
        _load_dotenv()
        
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        
        try:
            with open(self.config_path, 'r') as f:
                self.config = yaml.safe_load(f)
            # Expand environment variables in all string values
            self.config = _expand_config(self.config)
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

    def get_max_pages(self) -> int:
        """Get max pages to paginate per search"""
        return int(self.get('search.max_pages', 1))

    def is_detail_salary_enabled(self) -> bool:
        """Check if detail salary fetch is enabled"""
        return bool(self.get('search.detail_salary_fetch', False))

    def get_detail_salary_timeout(self) -> int:
        """Get detail salary fetch timeout in seconds"""
        return int(self.get('search.detail_salary_timeout', 5))

    def get_detail_salary_retries(self) -> int:
        """Get detail salary fetch retries"""
        return int(self.get('search.detail_salary_retries', 1))

    def get_detail_salary_max_per_query(self) -> int:
        """Get max detail salary fetches per query"""
        return int(self.get('search.detail_salary_max_per_query', 10))

    def get_detail_salary_delay_min(self) -> float:
        """Get minimum delay between detail salary fetches in seconds"""
        return float(self.get('search.detail_salary_delay_min', 1.0))

    def get_detail_salary_delay_max(self) -> float:
        """Get maximum delay between detail salary fetches in seconds"""
        return float(self.get('search.detail_salary_delay_max', 2.0))

    def is_detail_description_enabled(self) -> bool:
        """Check if detail description fetch is enabled"""
        return bool(self.get('search.detail_description_fetch', False))

    def get_detail_description_timeout(self) -> int:
        """Get detail description fetch timeout in seconds"""
        return int(self.get('search.detail_description_timeout', 8))

    def get_detail_description_retries(self) -> int:
        """Get detail description fetch retries"""
        return int(self.get('search.detail_description_retries', 1))

    def get_detail_description_max_per_query(self) -> int:
        """Get max detail description fetches per query"""
        return int(self.get('search.detail_description_max_per_query', 10))

    def get_detail_description_delay_min(self) -> float:
        """Get minimum delay between detail description fetches in seconds"""
        return float(self.get('search.detail_description_delay_min', 1.0))

    def get_detail_description_delay_max(self) -> float:
        """Get maximum delay between detail description fetches in seconds"""
        return float(self.get('search.detail_description_delay_max', 2.0))
    
    def get_job_boards(self) -> List[str]:
        """Get list of job boards to search"""
        return self.get('search.job_boards', ['target-site'])
    
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

    def get_navigation_timeout(self) -> int:
        """Get navigation timeout in milliseconds"""
        return self.get('browser.navigation_timeout', 45) * 1000

    def get_launch_timeout(self) -> int:
        """Get browser launch timeout in milliseconds"""
        return self.get('browser.launch_timeout', 60) * 1000

    def get_max_retries(self) -> int:
        """Get max retries for navigation/extraction"""
        return int(self.get('browser.max_retries', 2))

    def get_browser_channel(self) -> str:
        """Get Playwright browser channel override"""
        return self.get('browser.channel', '')

    def get_browser_executable_path(self) -> str:
        """Get browser executable path override"""
        return self.get('browser.executable_path', '')

    def use_stealth(self) -> bool:
        """Check if Playwright stealth should be enabled"""
        return self.get('browser.use_stealth', False)

    def use_undetected(self) -> bool:
        """Check if undetected Playwright should be enabled"""
        return self.get('browser.use_undetected', False)

    # === Proxy Config ===

    def proxy_enabled(self) -> bool:
        return bool(self.get('proxy.enabled', False))

    def get_proxy_config(self) -> dict:
        return dict(self.get('proxy', {}) or {})

    # === Captcha Solver Config ===

    def captcha_enabled(self) -> bool:
        return bool(self.get('captcha.enabled', False))

    def get_captcha_config(self) -> dict:
        return dict(self.get('captcha', {}) or {})

    # === FlareSolverr Config ===

    def get_flaresolverr_config(self) -> dict:
        """
        Get FlareSolverr configuration.

        Backwards-compat: if `flaresolverr.url` is empty, fall back to
        `cloudflare.flaresolverr_url` (legacy setting).
        """
        cfg = dict(self.get("flaresolverr", {}) or {})
        if not cfg.get("url"):
            legacy = (self.get("cloudflare.flaresolverr_url", "") or "").strip()
            if legacy:
                cfg["url"] = legacy
        return cfg

    def flaresolverr_enabled(self) -> bool:
        return bool(self.get("flaresolverr.enabled", False))
    
    # === AI Config ===
    
    def is_ai_enabled(self) -> bool:
        """Check if AI filtering is enabled"""
        return self.get('ai_filter.enabled', False)
    
    def get_ai_model(self) -> str:
        """Get AI model name"""
        return self.get('ai_filter.model', 'deepseek-coder-v2:latest')

    def get_ai_backend(self) -> str:
        """Get AI backend (ollama or groq)"""
        return self.get('ai_filter.backend', 'ollama')
    
    def get_ai_prompt(self) -> str:
        """Get AI scoring prompt template"""
        return self.get('ai_filter.scoring_prompt', '')

    def get_ai_max_retries(self) -> int:
        """Get max retries for AI scoring calls"""
        return int(self.get('ai_filter.max_retries', 2))

    def get_ai_max_reasoning_chars(self) -> int:
        """Get max characters to keep for AI reasoning"""
        return int(self.get('ai_filter.max_reasoning_chars', 400))

    def get_ai_debug(self) -> bool:
        """Check if AI debug logging is enabled"""
        return bool(self.get('ai_filter.debug', False))

    def is_ai_reasoning_enabled(self) -> bool:
        """Check if AI reasoning should be included"""
        return bool(self.get('ai_filter.include_reasoning', True))

    # === Dedupe Config ===

    def is_dedupe_enabled(self) -> bool:
        """Check if cross-run dedupe is enabled"""
        return self.get('dedupe.enabled', False)

    def get_dedupe_path(self) -> Path:
        """Get dedupe hash log path"""
        path = self.get('dedupe.hash_file', '')
        return Path(path) if path else None
    
    # === Vault Sync Config ===

    def is_vault_sync_enabled(self) -> bool:
        """Check if Obsidian vault sync is enabled"""
        return self.get('output.vault_sync.enabled', False)

    def get_vault_path(self) -> Path:
        """Get Obsidian vault path for syncing output"""
        path = self.get('output.vault_sync.vault_path', '')
        return Path(path) if path else None

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
