"""Ingestion trigger API endpoints.

Exposes endpoints to trigger asynchronous extraction across registered ingestors,
normalize data, refresh cache, and return execution summaries.
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from app.schemas.normalized_data import IngestionResponseSummary
from app.services.ingestion_service import IngestionService

router = APIRouter()


def get_ingestion_service() -> IngestionService:
    """Dependency injection provider for IngestionService."""
    return IngestionService()


@router.post(
    "/trigger",
    response_model=IngestionResponseSummary,
    status_code=status.HTTP_200_OK,
    summary="Trigger Multi-Source Ingestion Pipeline",
    description=(
        "Concurrently triggers extraction across external REST APIs and Web Scrapers, "
        "normalizes all records into canonical Pydantic models, updates Redis cache with "
        "configured TTL, and returns execution metrics."
    ),
)
async def trigger_ingestion(
    source: Optional[str] = Query(
        default=None,
        description="Filter to run a specific source ('api', 'scraper', or None for all)",
    ),
    service: IngestionService = Depends(get_ingestion_service),
) -> IngestionResponseSummary:
    """Execute concurrent ingestion pipeline and return summary stats."""
    _, summary = await service.run_ingestion(source_filter=source)
    return summary

