"""
AI Scorer - Local LLM scoring for job descriptions
"""

from __future__ import annotations

import logging
import json
import re
from typing import Optional, Tuple, List

import ollama

from models import Job

logger = logging.getLogger(__name__)

SCORE_PATTERN = re.compile(r"\b(10|[1-9])\b")


class AIScorer:
    """Scores jobs using a local LLM via Ollama."""

    def __init__(self, config) -> None:
        self.config = config
        self.model = config.get_ai_model()
        self.prompt_template = config.get_ai_prompt()
        self.max_retries = config.get_ai_max_retries()
        self.max_reasoning_chars = config.get_ai_max_reasoning_chars()
        self.debug = config.get_ai_debug()
        self.include_reasoning = config.is_ai_reasoning_enabled()
        self.available = self._check_ollama()

    def score_jobs(self, jobs: List[Job]) -> List[Job]:
        """Score all jobs in-place and return the list."""
        if not jobs:
            return jobs
        if not self.available:
            logger.warning("AI scoring skipped: Ollama not available")
            return jobs

        scored = 0
        for job in jobs:
            if not job.description:
                continue
            score, reasoning = self._score_job(job)
            if score is not None:
                job.ai_score = score
                job.ai_reasoning = reasoning
                scored += 1

        logger.info("AI scoring complete: %s/%s jobs scored", scored, len(jobs))
        return jobs

    def _score_job(self, job: Job) -> Tuple[Optional[int], Optional[str]]:
        prompt = self._build_prompt(job)

        for attempt in range(1, self.max_retries + 1):
            try:
                response = ollama.generate(model=self.model, prompt=prompt)
                text = (response.get("response") or "").strip()
                if self.debug:
                    logger.debug("AI raw response for %s: %s", job.title, text)
                score, reasoning = self._parse_response(text)
                if score is None and text:
                    logger.warning("AI score parse failed for %s", job.title)
                if not text:
                    logger.warning("AI response empty for %s", job.title)
                if not self.include_reasoning:
                    reasoning = None
                return score, reasoning
            except Exception as exc:
                logger.warning("AI scoring failed (attempt %s/%s): %s", attempt, self.max_retries, exc)

        return None, None

    def _build_prompt(self, job: Job) -> str:
        return self.prompt_template.format(
            title=job.title,
            company=job.company,
            location=job.location,
            description=job.description,
        )

    def _parse_response(self, text: str) -> Tuple[Optional[int], Optional[str]]:
        if not text:
            return None, None

        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\\s*|\\s*```$", "", cleaned, flags=re.IGNORECASE | re.DOTALL).strip()

        payload = None
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        if not isinstance(payload, dict):
            match = re.search(r"\\{.*\\}", cleaned, flags=re.DOTALL)
            if match:
                try:
                    payload = json.loads(match.group(0))
                except Exception:
                    payload = None

        if isinstance(payload, dict):
            include = payload.get("include")
            decision = payload.get("decision")
            score = payload.get("score")
            reason = payload.get("reason")
            if include is None and isinstance(decision, str):
                include = decision.strip().lower() in ("include", "keep", "yes", "true")
            try:
                score = int(score) if score is not None else None
            except (TypeError, ValueError):
                score = None
            reason_text = (str(reason).strip() if reason else None)
            if reason_text:
                reason_text = reason_text[: self.max_reasoning_chars]
            if isinstance(include, bool) and include is False:
                score = 0
                if reason_text:
                    if not reason_text.lower().startswith("exclude"):
                        reason_text = f"EXCLUDE: {reason_text}"
                else:
                    reason_text = "EXCLUDE"
            return score, reason_text

        score_match = re.search(r"\"score\"\\s*:\\s*(\\d+)", cleaned, flags=re.IGNORECASE)
        include_match = re.search(r"\"include\"\\s*:\\s*(true|false)", cleaned, flags=re.IGNORECASE)
        reason_match = re.search(r"\"reason\"\\s*:\\s*\"(.*?)\"", cleaned, flags=re.DOTALL)

        score = int(score_match.group(1)) if score_match else None
        include = None
        if include_match:
            include = include_match.group(1).lower() == "true"
        reason_text = reason_match.group(1).strip() if reason_match else None
        if reason_text:
            reason_text = reason_text[: self.max_reasoning_chars]

        if include is False:
            score = 0
            if reason_text:
                if not reason_text.lower().startswith("exclude"):
                    reason_text = f"EXCLUDE: {reason_text}"
            else:
                reason_text = "EXCLUDE"

        if score is not None:
            return score, reason_text

        match = SCORE_PATTERN.search(cleaned)
        score = int(match.group(1)) if match else None
        if score is None:
            return None, None
        reason_text = self._extract_reasoning(cleaned, score)
        return score, reason_text

    def _extract_reasoning(self, text: str, score: Optional[int]) -> Optional[str]:
        if not text:
            return None
        if score is None:
            return text[: self.max_reasoning_chars]

        # Remove the first score occurrence to keep the remaining explanation.
        reasoning = SCORE_PATTERN.sub("", text, count=1).strip()
        if not reasoning:
            return None
        return reasoning[: self.max_reasoning_chars]

    def _check_ollama(self) -> bool:
        try:
            ollama.list()
            return True
        except Exception as exc:
            logger.warning("Ollama not reachable: %s", exc)
            return False
