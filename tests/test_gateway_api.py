"""Integration and API gateway tests.

Tests FastAPI endpoints:
- GET /api/v1/health (healthy and degraded states)
- POST /api/v1/ingest/trigger (concurrent execution, error handling)
- GET /api/v1/data/aggregated (cache hit, cache miss fallback, force refresh, filtering)
"""

from unittest.mock import patch
import httpx
import pytest
import respx
from app.core.config import get_settings
from app.core.redis import RedisManager
from app.services.cache_service import CacheService


@pytest.mark.asyncio
async def test_root_endpoint(async_client: httpx.AsyncClient) -> None:
    """Test service root metadata endpoint."""
    response = await async_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "operational"
    assert "documentation" in data
    assert "endpoints" in data


@pytest.mark.asyncio
async def test_health_endpoint_healthy(async_client: httpx.AsyncClient) -> None:
    """Test GET /api/v1/health returns healthy when Redis is reachable."""
    response = await async_client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["redis_connected"] is True
    assert data["redis_latency_ms"] is not None


@pytest.mark.asyncio
async def test_health_endpoint_degraded(async_client: httpx.AsyncClient) -> None:
    """Test GET /api/v1/health returns degraded when Redis ping fails."""
    with patch.object(RedisManager, "ping", return_value=(False, None)):
        response = await async_client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["redis_connected"] is False
        assert data["redis_latency_ms"] is None


@pytest.mark.asyncio
async def test_ingest_trigger_endpoint_success(
    async_client: httpx.AsyncClient,
    sample_exchange_api_json: dict,
    sample_hn_html: str,
) -> None:
    """Test POST /api/v1/ingest/trigger successfully executes all ingestors concurrently."""
    settings = get_settings()
    api_url = f"{settings.EXTERNAL_API_BASE_URL.rstrip('/')}/latest?from=USD"
    scrape_url = settings.SCRAPING_TARGET_URL

    with respx.mock:
        respx.get(api_url).respond(200, json=sample_exchange_api_json)
        respx.get(scrape_url).respond(200, html=sample_hn_html)

        response = await async_client.post("/api/v1/ingest/trigger")

    assert response.status_code == 200
    summary = response.json()
    assert summary["status"] == "success"
    # Exchange rates (5) + Scraper (2) = 7 records
    assert summary["total_records"] >= 7
    assert summary["duration_ms"] > 0
    assert "api_exchange_rates" in summary["sources_processed"]
    assert "web_scraper_tech_news" in summary["sources_processed"]
    assert len(summary["errors"]) == 0


@pytest.mark.asyncio
async def test_aggregated_data_cache_miss_then_cache_hit(
    async_client: httpx.AsyncClient,
    sample_exchange_api_json: dict,
    sample_hn_html: str,
) -> None:
    """Test GET /api/v1/data/aggregated auto-triggers ingestion on cache miss, then serves cache hit."""
    settings = get_settings()
    api_url = f"{settings.EXTERNAL_API_BASE_URL.rstrip('/')}/latest?from=USD"
    scrape_url = settings.SCRAPING_TARGET_URL

    with respx.mock:
        api_route = respx.get(api_url).respond(200, json=sample_exchange_api_json)
        scrape_route = respx.get(scrape_url).respond(200, html=sample_hn_html)

        # 1. First Call: Cache Miss -> Fallback to live extraction
        resp1 = await async_client.get("/api/v1/data/aggregated")
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["success"] is True
        assert data1["cached"] is False  # Cache miss
        assert data1["total"] >= 7
        assert len(data1["data"]) >= 7

        assert api_route.called
        assert scrape_route.called

        # 2. Second Call: Cache Hit -> Serves directly from Redis without network calls
        api_route.reset()
        scrape_route.reset()

        resp2 = await async_client.get("/api/v1/data/aggregated")
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["success"] is True
        assert data2["cached"] is True  # Cache HIT!
        assert data2["cache_ttl_remaining"] is not None
        assert data2["total"] == data1["total"]

        # Assert no additional outbound HTTP calls were made
        assert not api_route.called
        assert not scrape_route.called


@pytest.mark.asyncio
async def test_aggregated_data_force_refresh(
    async_client: httpx.AsyncClient,
    sample_exchange_api_json: dict,
    sample_hn_html: str,
) -> None:
    """Test that ?fresh=true forces a cache refresh."""
    settings = get_settings()
    api_url = f"{settings.EXTERNAL_API_BASE_URL.rstrip('/')}/latest?from=USD"
    scrape_url = settings.SCRAPING_TARGET_URL

    with respx.mock:
        respx.get(api_url).respond(200, json=sample_exchange_api_json)
        respx.get(scrape_url).respond(200, html=sample_hn_html)

        # Prime cache
        await async_client.post("/api/v1/ingest/trigger")

        # Query with fresh=true
        resp = await async_client.get("/api/v1/data/aggregated?fresh=true")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cached"] is False


@pytest.mark.asyncio
async def test_aggregated_data_source_filtering_and_pagination(
    async_client: httpx.AsyncClient,
    sample_exchange_api_json: dict,
    sample_hn_html: str,
) -> None:
    """Test filtering by source and paginating results via limit and offset."""
    settings = get_settings()
    api_url = f"{settings.EXTERNAL_API_BASE_URL.rstrip('/')}/latest?from=USD"
    scrape_url = settings.SCRAPING_TARGET_URL

    with respx.mock:
        respx.get(api_url).respond(200, json=sample_exchange_api_json)
        respx.get(scrape_url).respond(200, html=sample_hn_html)

        # Trigger ingestion
        await async_client.post("/api/v1/ingest/trigger")

        # Query filtered to api source with pagination limit=2, offset=0
        resp = await async_client.get("/api/v1/data/aggregated?source=rates&limit=2&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]) == 2
        for record in data["data"]:
            assert record["source"] == "api_exchange_rates"

        # Query with offset=2
        resp_offset = await async_client.get("/api/v1/data/aggregated?source=rates&limit=2&offset=2")
        assert resp_offset.status_code == 200
        data_offset = resp_offset.json()
        assert len(data_offset["data"]) == 2
        # Verify page items are different
        assert data["data"][0]["id"] != data_offset["data"][0]["id"]

