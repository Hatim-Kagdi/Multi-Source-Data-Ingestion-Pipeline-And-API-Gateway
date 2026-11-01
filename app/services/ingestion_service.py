"""Ingestion Orchestration and Normalization Service.

Coordinates concurrent asynchronous extraction across disparate data sources
(REST API, Web Scraping), deduplicates and standardizes records, and manages
the Redis cache synchronization lifecycle.
"""

import asyncio
from datetime import datetime, timezone
import time
from typing import Dict, List, Optional, Tuple
import httpx

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.ingestors.api_client import APIClient
from app.ingestors.base import BaseIngestor
from app.ingestors.web_scraper import WebScraper
from app.schemas.normalized_data import (
    AggregatedDataResponse,
    IngestionErrorDetail,
    IngestionResponseSummary,
    NormalizedRecord,
)
from app.services.cache_service import CacheService

logger = get_logger(__name__)


class IngestionService:
    """Orchestrates multi-source extraction, concurrency, and caching."""

    CACHE_KEY_ALL = "data_gateway:aggregated:all"
    CACHE_KEY_SOURCE_PREFIX = "data_gateway:source:"

    def __init__(
        self,
        api_client: Optional[APIClient] = None,
        web_scraper: Optional[WebScraper] = None,
        cache_service: Optional[CacheService] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.cache_service = cache_service or CacheService(settings=self.settings)
        self.api_client = api_client or APIClient(settings=self.settings)
        self.web_scraper = web_scraper or WebScraper(settings=self.settings)

    @classmethod
    def get_source_cache_key(cls, source_name: str) -> str:
        """Construct the Redis key for a specific ingestion source."""
        return f"{cls.CACHE_KEY_SOURCE_PREFIX}{source_name}"

    async def run_ingestion(
        self,
        source_filter: Optional[str] = None,
    ) -> Tuple[List[NormalizedRecord], IngestionResponseSummary]:
        """Execute concurrent extraction across registered ingestor engines.

        Uses asyncio.gather with return_exceptions=True to ensure partial failures
        do not crash the entire ingestion pipeline.
        """
        start_time = time.perf_counter()
        logger.info(
            f"[IngestionService] Triggering ingestion run (source_filter='{source_filter or 'ALL'}')"
        )

        # Determine which ingestors to execute
        active_ingestors: List[BaseIngestor] = []
        if not source_filter or source_filter.lower() in ("all", "all_sources"):
            active_ingestors = [self.api_client, self.web_scraper]
        elif source_filter.lower() in ("api", "rates", "api_exchange_rates"):
            active_ingestors = [self.api_client]
        elif source_filter.lower() in ("scraper", "news", "web_scraper_tech_news"):
            active_ingestors = [self.web_scraper]
        else:
            # Match by source_name substring
            active_ingestors = [
                ing for ing in (self.api_client, self.web_scraper)
                if source_filter.lower() in ing.source_name.lower()
            ]
            if not active_ingestors:
                active_ingestors = [self.api_client, self.web_scraper]

        sources_processed: List[str] = []
        errors: List[IngestionErrorDetail] = []
        all_records: List[NormalizedRecord] = []

        # Execute concurrent tasks
        tasks = [ingestor.fetch_and_normalize() for ingestor in active_ingestors]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process each ingestor output
        for ingestor, result in zip(active_ingestors, results):
            sources_processed.append(ingestor.source_name)

            if isinstance(result, Exception):
                logger.error(
                    f"[IngestionService] Ingestor '{ingestor.source_name}' failed: {result}",
                    exc_info=result,
                )
                errors.append(
                    IngestionErrorDetail(
                        source=ingestor.source_name,
                        error_type=type(result).__name__,
                        message=str(result),
                        details={"category": ingestor.category},
                    )
                )
            elif isinstance(result, list):
                logger.info(
                    f"[IngestionService] Ingestor '{ingestor.source_name}' produced {len(result)} records"
                )
                # Cache individual source records
                source_key = self.get_source_cache_key(ingestor.source_name)
                await self.cache_service.set_normalized_records(
                    source_key,
                    result,
                    ttl=self.settings.REDIS_CACHE_TTL_SECONDS,
                )
                all_records.extend(result)

        # Deduplicate records by unique deterministic ID
        dedup_map: Dict[str, NormalizedRecord] = {}
        for rec in all_records:
            dedup_map[rec.id] = rec
        deduped_records = list(dedup_map.values())

        # Cache aggregated collection if we have records
        if deduped_records:
            await self.cache_service.set_normalized_records(
                self.CACHE_KEY_ALL,
                deduped_records,
                ttl=self.settings.REDIS_CACHE_TTL_SECONDS,
            )

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Compute execution status
        if not errors:
            status = "success"
        elif len(errors) < len(active_ingestors):
            status = "partial_failure"
        else:
            status = "failed"

        summary = IngestionResponseSummary(
            status=status,
            total_records=len(deduped_records),
            duration_ms=duration_ms,
            timestamp=datetime.now(timezone.utc),
            sources_processed=sources_processed,
            errors=errors,
        )

        logger.info(
            f"[IngestionService] Ingestion run completed: status={status}, "
            f"records={len(deduped_records)}, duration={duration_ms}ms"
        )
        return deduped_records, summary

    async def get_aggregated_data(
        self,
        source: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        force_refresh: bool = False,
    ) -> AggregatedDataResponse:
        """Retrieve normalized data from Redis cache or automatically fallback to fetch.

        If cached dataset is available and force_refresh is False, serves directly
        from Redis. Otherwise triggers full ingestion and updates cache before returning.
        """
        # Determine cache key based on source filter
        if source:
            # Normalize target key
            matching_source = None
            for ing in (self.api_client, self.web_scraper):
                if source.lower() in ing.source_name.lower():
                    matching_source = ing.source_name
                    break
            target_source = matching_source or source
            cache_key = self.get_source_cache_key(target_source)
        else:
            target_source = None
            cache_key = self.CACHE_KEY_ALL

        records: Optional[List[NormalizedRecord]] = None
        is_cached = False
        ttl_remaining: Optional[int] = None

        # Check Redis Cache
        if not force_refresh:
            records = await self.cache_service.get_normalized_records(cache_key)
            if records is not None:
                is_cached = True
                raw_ttl = await self.cache_service.ttl(cache_key)
                ttl_remaining = raw_ttl if raw_ttl >= 0 else None

        # Cache Miss or Force Refresh: Trigger Pipeline
        if records is None:
            logger.info(
                f"[IngestionService] Cache miss or force_refresh for '{cache_key}'. "
                f"Executing fallback ingestion..."
            )
            extracted_records, _ = await self.run_ingestion(source_filter=target_source)

            # If filtered by source, fetch from that source cache or filter list
            if target_source:
                records = [r for r in extracted_records if target_source.lower() in r.source.lower()]
            else:
                records = extracted_records

            is_cached = False
            ttl_remaining = self.settings.REDIS_CACHE_TTL_SECONDS

        total_count = len(records)
        paged_records = records[offset : offset + limit]

        return AggregatedDataResponse(
            success=True,
            source=target_source,
            total=total_count,
            cached=is_cached,
            cache_ttl_remaining=ttl_remaining,
            data=paged_records,
        )

