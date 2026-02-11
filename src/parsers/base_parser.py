"""Base parser class with shared retry logic and file I/O."""

import json
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from src.config_loader import load_config


class BaseParser(ABC):
    """
    Abstract base class for platform-specific parsers.

    Subclasses must implement:
        - parse_single(url) -> dict
        - platform_name (property)
    """

    def __init__(self, config: dict = None):
        self.config = config or load_config()
        self.logger = logging.getLogger(self.__class__.__name__)

        retry_cfg = self.config.get("retry", {})
        self.max_retries = retry_cfg.get("max_retries", 3)
        self.backoff_base = retry_cfg.get("backoff_base", 2)
        self.backoff_max = retry_cfg.get("backoff_max", 60)

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the platform identifier, e.g. 'youtube' or 'instagram'."""
        ...

    @abstractmethod
    def parse_single(self, url: str) -> dict:
        """
        Parse a single URL and return structured data.

        Returns dict with parsed fields. Failed parses include an 'error' key.
        """
        ...

    def parse_batch(self, urls: list[str]) -> list[dict]:
        """Parse a list of URLs, collecting results and errors."""
        results = []
        total = len(urls)
        for i, url in enumerate(urls, 1):
            self.logger.info("Parsing %d/%d: %s", i, total, url)
            result = self._retry_parse(url)
            results.append(result)
        return results

    def _retry_parse(self, url: str) -> dict:
        """Attempt to parse a URL with exponential backoff retry."""
        last_exception = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return self.parse_single(url)
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries:
                    wait = min(
                        self.backoff_base ** attempt,
                        self.backoff_max,
                    )
                    self.logger.warning(
                        "Attempt %d/%d failed for %s: %s. Retrying in %.1fs...",
                        attempt, self.max_retries, url, str(e), wait,
                    )
                    time.sleep(wait)
                else:
                    self.logger.error(
                        "All %d attempts failed for %s: %s",
                        self.max_retries, url, str(e),
                    )
        return {
            "url": url,
            "platform": self.platform_name,
            "error": str(last_exception),
        }

    def save_results(self, results: list[dict], output_path: str) -> Path:
        """Save parsed results to a JSON file."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)
        self.logger.info("Saved %d results to %s", len(results), path)
        return path
