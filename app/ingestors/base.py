"""Abstract Base Class for Data Ingestion Engines.

Defines the contract and common normalization utilities that all data extractors
(API clients, web scrapers, message bus consumers) must implement.
"""

from abc import ABC, abstractmethod
import hashlib
import json
import time
from typing import Any, List
from app.core.logging import get_logger
from app.schemas.normalized_data import NormalizedRecord, SourceType

logger = get_logger(__name__)


class BaseIngestor(ABC):
    """Abstract base class establishing lifecycle methods for data ingestors."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique identifying name for this ingestor source."""
        pass

    @property
    @abstractmethod
    def source_type(self) -> SourceType:
        """Category type of the ingestor (REST_API, WEB_SCRAPER)."""
        pass

    @property
    def category(self) -> str:
        """Domain classification for extracted data (e.g. 'financial', 'tech_news')."""
        return "general"

    @abstractmethod
    async def extract(self) -> Any:
        """Extract raw data from external source.

        Must be implemented asynchronously using httpx.AsyncClient or asyncio.
        """
        pass

    @abstractmethod
    def normalize(self, raw_data: Any) -> List[NormalizedRecord]:
        """Transform raw extracted data into unified NormalizedRecord DTOs."""
        pass

    async def fetch_and_normalize(self) -> List[NormalizedRecord]:
        """Execute full extraction and normalization pipeline for this source.

        Measures timing, enforces contract validation, and logs structured metrics.
        """
        logger.info(f"[{self.source_name}] Starting ingestion pipeline...")
        start_time = time.perf_counter()

        raw_data = await self.extract()
        records = self.normalize(raw_data)

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.info(
            f"[{self.source_name}] Ingestion complete: "
            f"extracted and normalized {len(records)} records in {elapsed_ms}ms"
        )
        return records

    @staticmethod
    def generate_id(source: str, unique_key: str) -> str:
        """Generate a deterministic SHA-256 hash ID based on source and key."""
        composite = f"{source}:{unique_key}"
        return hashlib.sha256(composite.encode("utf-8")).hexdigest()

    @staticmethod
    def compute_checksum(payload: Any) -> str:
        """Compute SHA-256 checksum of payload for change detection."""
        encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

