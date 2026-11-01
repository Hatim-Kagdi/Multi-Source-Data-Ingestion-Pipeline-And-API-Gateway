"""Pytest configuration and test fixtures.

Provides test-isolated mocks for Redis (via fakeredis.aioredis), HTTP client fixtures,
canned mock HTML and JSON payloads, and an asynchronous ASGI test client.
"""

from typing import AsyncGenerator, Dict, Any
import pytest
import pytest_asyncio
import httpx
import fakeredis.aioredis as fake_aioredis

from app.core.config import Settings, get_settings
from app.core.redis import RedisManager
from app.main import app
from app.services.cache_service import CacheService


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Fixture providing testing configuration with shortened timeouts and retries."""
    return Settings(
        ENVIRONMENT="testing",
        DEBUG=True,
        HTTP_MAX_RETRIES=2,
        HTTP_BACKOFF_FACTOR=0.001,  # Ultra-fast backoff in tests
        HTTP_TIMEOUT_SECONDS=1.0,
        REDIS_CACHE_TTL_SECONDS=60,
    )


@pytest_asyncio.fixture
async def fake_redis() -> AsyncGenerator[fake_aioredis.FakeRedis, None]:
    """Isolated async in-memory Redis client using fakeredis."""
    client = fake_aioredis.FakeRedis(decode_responses=True)
    RedisManager.set_client(client)
    yield client
    await client.flushall()
    await client.aclose()


@pytest_asyncio.fixture
async def cache_service(
    fake_redis: fake_aioredis.FakeRedis,
    test_settings: Settings,
) -> CacheService:
    """Configured CacheService bound to the fake Redis instance."""
    return CacheService(redis_client=fake_redis, settings=test_settings)


@pytest.fixture
def sample_exchange_api_json() -> Dict[str, Any]:
    """Mock JSON response payload from exchange rates API."""
    return {
        "amount": 1.0,
        "base": "USD",
        "date": "2026-11-01",
        "rates": {
            "EUR": 0.9250,
            "GBP": 0.7920,
            "JPY": 154.50,
            "CAD": 1.3840,
            "INR": 83.45,
        },
    }


@pytest.fixture
def sample_hn_html() -> str:
    """Realistic HTML DOM string representing Hacker News layout."""
    return """
    <html>
        <body>
            <table class="itemlist">
                <tr class="athing" id="38291001">
                    <td class="title">
                        <span class="titleline">
                            <a href="https://github.com/fastapi/fastapi">FastAPI: Modern High-Performance Python Framework</a>
                        </span>
                    </td>
                </tr>
                <tr>
                    <td class="subtext">
                        <span class="score" id="score_38291001">450 points</span> by <a href="#" class="hnuser">tiangolo</a>
                        | <a href="#">182 comments</a>
                    </td>
                </tr>
                <tr class="athing" id="38291002">
                    <td class="title">
                        <span class="titleline">
                            <a href="https://redis.io">Redis 8 Released with AsyncIO Multi-Threaded Engine</a>
                        </span>
                    </td>
                </tr>
                <tr>
                    <td class="subtext">
                        <span class="score" id="score_38291002">320 points</span> by <a href="#" class="hnuser">antirez</a>
                        | <a href="#">95 comments</a>
                    </td>
                </tr>
            </table>
        </body>
    </html>
    """


@pytest.fixture
def sample_altered_html() -> str:
    """Altered/malformed HTML DOM string with missing selectors, partial tags, and altered classes."""
    return """
    <html>
        <body>
            <div class="unrelated-wrapper">
                <tr class="athing" id="broken_item_1">
                    <!-- Missing titleline span, but contains direct link -->
                    <td class="title">
                        <a href="https://example.com/item1">Direct Title Link Without Span</a>
                    </td>
                </tr>
                <tr>
                    <td class="subtext">
                        <!-- Missing score element, only user and comments -->
                        by <a href="#" class="hnuser">anonymous_dev</a> | <a href="#">12 comments</a>
                    </td>
                </tr>
                <tr class="athing" id="broken_item_2">
                    <!-- Completely empty title cell -->
                    <td class="title"></td>
                </tr>
                <tr>
                    <td class="subtext">
                        <span class="score">10 points</span>
                    </td>
                </tr>
                <!-- Generic modern article layout fallback -->
                <article>
                    <h2><a href="https://example.com/blog/python-async">Asynchronous Python Ingestion at Scale</a></h2>
                    <p>Some snippet text here</p>
                </article>
            </div>
        </body>
    </html>
    """


@pytest_asyncio.fixture
async def async_client(
    fake_redis: fake_aioredis.FakeRedis,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Asynchronous HTTP test client bound to the FastAPI application with mock Redis."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

