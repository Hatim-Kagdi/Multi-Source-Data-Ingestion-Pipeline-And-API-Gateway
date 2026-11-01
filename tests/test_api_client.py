"""Unit tests for the REST API client ingestor.

Tests HTTP resilience, exponential backoff retries, rate-limiting (429),
server error recovery (5xx), connection timeouts, and fallback defaults using respx.
"""

import httpx
import pytest
import respx
from app.core.config import Settings
from app.ingestors.api_client import APIClient
from app.schemas.normalized_data import SourceType
from app.schemas.raw_data import RawAPIPayload


@pytest.mark.asyncio
async def test_api_client_extract_success(
    test_settings: Settings,
    sample_exchange_api_json: dict,
) -> None:
    """Test successful API extraction under standard 200 OK conditions."""
    client = APIClient(settings=test_settings)
    target_url = client.endpoint

    with respx.mock:
        respx.get(target_url).respond(status_code=200, json=sample_exchange_api_json)
        raw_payload = await client.extract()

    assert isinstance(raw_payload, RawAPIPayload)
    assert raw_payload.base == "USD"
    assert "EUR" in raw_payload.rates
    assert raw_payload.rates["EUR"] == 0.9250
    assert raw_payload.raw_response == sample_exchange_api_json


@pytest.mark.asyncio
async def test_api_client_normalize(
    test_settings: Settings,
    sample_exchange_api_json: dict,
) -> None:
    """Test normalization from RawAPIPayload to canonical NormalizedRecord list."""
    client = APIClient(settings=test_settings)
    raw = RawAPIPayload(
        amount=1.0,
        base="USD",
        date="2026-11-01",
        rates=sample_exchange_api_json["rates"],
        raw_response=sample_exchange_api_json,
    )

    records = client.normalize(raw)

    assert len(records) == len(sample_exchange_api_json["rates"])
    for rec in records:
        assert rec.source == "api_exchange_rates"
        assert rec.source_type == SourceType.REST_API
        assert rec.category == "financial"
        assert rec.id.isalnum()
        assert rec.checksum.isalnum()
        assert rec.payload["base_currency"] == "USD"
        assert "target_currency" in rec.payload
        assert "rate" in rec.payload


@pytest.mark.asyncio
async def test_api_client_retry_on_429_rate_limit(
    test_settings: Settings,
    sample_exchange_api_json: dict,
) -> None:
    """Test retry behavior when external service encounters HTTP 429 Too Many Requests."""
    client = APIClient(settings=test_settings)
    target_url = client.endpoint

    with respx.mock:
        # First attempt returns 429 with Retry-After: 0, second succeeds with 200
        route = respx.get(target_url)
        route.side_effect = [
            httpx.Response(429, headers={"Retry-After": "0"}, json={"message": "Rate limit exceeded"}),
            httpx.Response(200, json=sample_exchange_api_json),
        ]

        raw_payload = await client.extract()

    assert route.call_count == 2
    assert raw_payload.base == "USD"
    assert "GBP" in raw_payload.rates


@pytest.mark.asyncio
async def test_api_client_retry_on_500_server_error(
    test_settings: Settings,
    sample_exchange_api_json: dict,
) -> None:
    """Test retry behavior when external server returns HTTP 500 error."""
    client = APIClient(settings=test_settings)
    target_url = client.endpoint

    with respx.mock:
        route = respx.get(target_url)
        route.side_effect = [
            httpx.Response(500, text="Internal Server Error"),
            httpx.Response(200, json=sample_exchange_api_json),
        ]

        raw_payload = await client.extract()

    assert route.call_count == 2
    assert raw_payload.base == "USD"


@pytest.mark.asyncio
async def test_api_client_persistent_failure_fallback(
    test_settings: Settings,
) -> None:
    """Test that exhausting retries activates safe baseline fallback without crashing."""
    client = APIClient(settings=test_settings)
    target_url = client.endpoint

    with respx.mock:
        # All retries fail with 503 Service Unavailable
        route = respx.get(target_url)
        route.return_value = httpx.Response(503, text="Service Unavailable")

        raw_payload = await client.extract()

    assert route.call_count == test_settings.HTTP_MAX_RETRIES
    assert raw_payload.raw_response is not None
    assert raw_payload.raw_response.get("fallback") is True
    assert "EUR" in raw_payload.rates

    # Verify normalization handles fallback flag gracefully
    records = client.normalize(raw_payload)
    assert len(records) > 0
    assert records[0].metadata.get("is_fallback") is True


@pytest.mark.asyncio
async def test_api_client_timeout_handling(
    test_settings: Settings,
) -> None:
    """Test graceful fallback behavior when external network calls time out."""
    client = APIClient(settings=test_settings)
    target_url = client.endpoint

    with respx.mock:
        route = respx.get(target_url)
        route.side_effect = httpx.ReadTimeout("Read connection timed out")

        raw_payload = await client.extract()

    assert route.call_count == test_settings.HTTP_MAX_RETRIES
    assert raw_payload.raw_response.get("fallback") is True
    assert "JPY" in raw_payload.rates

