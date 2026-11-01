"""Data aggregation query API endpoints.

Exposes endpoints to query normalized records from Redis cache with automatic
fallback live extraction on cache miss.
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from app.schemas.normalized_data import AggregatedDataResponse
from app.services.ingestion_service import IngestionService

router = APIRouter()


def get_ingestion_service() -> IngestionService:
    """Dependency injection provider for IngestionService."""
    return IngestionService()


@router.get(
    "/aggregated",
    response_model=AggregatedDataResponse,
    status_code=status.HTTP_200_OK,
    summary="Query Processed Normalized Dataset",
    description=(
        "Retrieves standardized records from the high-speed Redis cache. "
        "If a cache miss occurs, automatically executes the ingestion pipeline "
        "as a transparent fallback, populates the cache, and serves the latest records."
    ),
)
async def get_aggregated_data(
    source: Optional[str] = Query(
        default=None,
        description="Filter records by source name (e.g., 'rates', 'scraper', or full source name)",
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=500,
        description="Maximum number of records to return per page",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Zero-based record offset index for pagination",
    ),
    fresh: bool = Query(
        default=False,
        description="Set to true to bypass Redis cache and force an immediate live ingestion run",
    ),
    service: IngestionService = Depends(get_ingestion_service),
) -> AggregatedDataResponse:
    """Retrieve normalized records from Redis cache or fallback ingestion."""
    return await service.get_aggregated_data(
        source=source,
        limit=limit,
        offset=offset,
        force_refresh=fresh,
    )

