"""
Data models for Job Bot
Defines structure for jobs, search results, and config
"""

from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, HttpUrl, Field


class Job(BaseModel):
    """Represents a single job posting"""
    
    title: str
    company: str
    location: str
    link: HttpUrl
    description: str = ""
    salary: Optional[str] = None
    
    # Metadata
    source: str = "target-site"  # Which job board
    date_posted: Optional[str] = None
    collected_at: datetime = Field(default_factory=datetime.now)
    
    # AI scoring (Phase 5)
    ai_score: Optional[int] = None  # 1-10 rating
    ai_reasoning: Optional[str] = None
    
    def __str__(self) -> str:
        return f"{self.title} at {self.company} ({self.location})"
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class SearchQuery(BaseModel):
    """Represents a job search query"""
    
    keyword: str
    location: str
    max_results: int = 50
    job_board: str = "target-site"
    
    def __str__(self) -> str:
        return f"'{self.keyword}' in {self.location}"


class SearchResults(BaseModel):
    """Container for all search results"""
    
    queries: List[SearchQuery]
    jobs: List[Job]
    total_jobs: int = 0
    timestamp: datetime = Field(default_factory=datetime.now)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
