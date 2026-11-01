"""Pydantic models representing raw un-normalized payloads from ingestors.

These DTOs capture data exactly as delivered by third-party APIs or extracted
directly from HTML DOM before standardization.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RawAPIPayload(BaseModel):
    """Raw DTO representing payload from external financial / rates REST API."""

    amount: float = Field(default=1.0, description="Base amount converted")
    base: str = Field(default="EUR", description="Base currency code")
    date: str = Field(default="", description="Rate quotation date")
    rates: Dict[str, float] = Field(default_factory=dict, description="Currency rate mapping")
    raw_response: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Full untouched raw JSON response dictionary",
    )


class RawScrapedItem(BaseModel):
    """Raw DTO representing single item extracted from web HTML DOM."""

    native_id: Optional[str] = Field(default=None, description="Native DOM or post ID")
    title: str = Field(description="Raw extracted text title")
    url: Optional[str] = Field(default=None, description="Target item link/href")
    author: Optional[str] = Field(default=None, description="Author or publisher username")
    score: Optional[int] = Field(default=None, description="Points, upvotes, or rating")
    comments_count: Optional[int] = Field(default=None, description="Total replies or comments")
    extracted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when DOM scraping took place",
    )


class RawIngestionBatch(BaseModel):
    """Container for a batch of raw records from a single extraction source."""

    source_name: str
    source_type: str
    items_count: int
    data: List[Any]
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

