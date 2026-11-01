"""Standardized unified Pydantic v2 DTOs for multi-source data ingestion.

Transforms heterogeneous sources (REST API JSON, HTML DOM elements) into a single,
canonical, validated data schema ready for querying and caching.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class SourceType(str, Enum):
    """Categorical type for data extraction sources."""

    REST_API = "rest_api"
    WEB_SCRAPER = "web_scraper"


class NormalizedRecord(BaseModel):
    """Canonical schema representing a single standardized ingested entity."""

    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
    )

    id: str = Field(
        description="Deterministic unique SHA-256 identifier (source + item identity)"
    )
    source: str = Field(
        description="Identifier of originating source (e.g., 'frankfurter_rates', 'hacker_news')"
    )
    source_type: SourceType = Field(
        description="Extraction medium category (REST API vs Web Scraper)"
    )
    category: str = Field(
        default="general",
        description="Logical business domain category (e.g. 'financial', 'tech_news')",
    )
    title: str = Field(
        description="Standardized headline, title, or currency pair descriptor"
    )
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Cleaned, structured key-value payload data",
    )
    url: Optional[str] = Field(
        default=None,
        description="Direct link to source document or resource, if applicable",
    )
    ingested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of when this record was normalized",
    )
    checksum: str = Field(
        description="Content checksum for deduplication and drift tracking"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Auxiliary metadata (HTTP latency, parser version, retry count)",
    )


class IngestionErrorDetail(BaseModel):
    """Details of an error encountered during a source ingestion run."""

    source: str
    error_type: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)


class IngestionResponseSummary(BaseModel):
    """Execution summary statistics returned by the ingestion trigger endpoint."""

    status: Literal["success", "partial_failure", "failed"] = Field(
        description="Overall execution status across all ingestor sources"
    )
    total_records: int = Field(
        description="Total count of successfully extracted and normalized records"
    )
    duration_ms: float = Field(
        description="Total wall-clock duration of concurrent ingestion run in ms"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Execution completion timestamp",
    )
    sources_processed: List[str] = Field(
        default_factory=list,
        description="Names of ingestor sources executed during this trigger",
    )
    errors: List[IngestionErrorDetail] = Field(
        default_factory=list,
        description="List of captured errors from failed source ingestors",
    )


class AggregatedDataResponse(BaseModel):
    """Response envelope for queried normalized datasets."""

    success: bool = True
    source: Optional[str] = Field(
        default=None,
        description="Source filter applied (or null if all sources aggregated)",
    )
    total: int = Field(
        description="Total number of items in response"
    )
    cached: bool = Field(
        description="Whether this dataset was served directly from Redis cache"
    )
    cache_ttl_remaining: Optional[int] = Field(
        default=None,
        description="Seconds remaining before Redis cache expiry",
    )
    data: List[NormalizedRecord] = Field(
        default_factory=list,
        description="List of canonical normalized records",
    )


class HealthResponse(BaseModel):
    """Health check status envelope."""

    status: Literal["healthy", "degraded", "unhealthy"] = Field(
        description="Operational health status of the application service"
    )
    app_version: str = Field(description="Current version of the application")
    environment: str = Field(description="Current runtime environment")
    redis_connected: bool = Field(
        description="Indicates whether Redis cache backend is reachable"
    )
    redis_latency_ms: Optional[float] = Field(
        default=None,
        description="Round-trip latency to Redis server in milliseconds",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Current UTC server time",
    )

