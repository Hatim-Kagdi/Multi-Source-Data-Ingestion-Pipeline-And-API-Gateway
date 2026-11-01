"""Unit tests for the Web Scraper ingestor.

Tests HTML DOM extraction using BeautifulSoup4 + lxml, tolerance for missing tags,
DOM layout shifts, custom headers, and network retry/fallback behaviors.
"""

import httpx
import pytest
import respx
from app.core.config import Settings
from app.ingestors.web_scraper import WebScraper
from app.schemas.normalized_data import SourceType
from app.schemas.raw_data import RawScrapedItem


@pytest.mark.asyncio
async def test_scraper_parse_dom_standard_hn(
    test_settings: Settings,
    sample_hn_html: str,
) -> None:
    """Test DOM parsing on standard Hacker News HTML table layout."""
    scraper = WebScraper(settings=test_settings)
    items = scraper._parse_dom(sample_hn_html)

    assert len(items) == 2

    first = items[0]
    assert isinstance(first, RawScrapedItem)
    assert first.native_id == "38291001"
    assert "FastAPI: Modern High-Performance" in first.title
    assert first.url == "https://github.com/fastapi/fastapi"
    assert first.author == "tiangolo"
    assert first.score == 450
    assert first.comments_count == 182

    second = items[1]
    assert second.native_id == "38291002"
    assert "Redis 8 Released" in second.title
    assert second.author == "antirez"
    assert second.score == 320
    assert second.comments_count == 95


@pytest.mark.asyncio
async def test_scraper_parse_dom_altered_and_missing_tags(
    test_settings: Settings,
    sample_altered_html: str,
) -> None:
    """Test DOM parsing resilience against missing tags, empty cells, and DOM layout shifts."""
    scraper = WebScraper(settings=test_settings)

    # Must complete cleanly without raising uncaught exceptions
    items = scraper._parse_dom(sample_altered_html)

    assert len(items) >= 1

    # First item had no .titleline span and no score tag
    item1 = next((i for i in items if i.native_id == "broken_item_1"), None)
    assert item1 is not None
    assert item1.title == "Direct Title Link Without Span"
    assert item1.url == "https://example.com/item1"
    assert item1.author == "anonymous_dev"
    assert item1.score is None  # Missing score handled gracefully
    assert item1.comments_count == 12

    # Item with empty title cell should be skipped cleanly
    broken_item_2 = next((i for i in items if i.native_id == "broken_item_2"), None)
    assert broken_item_2 is None


@pytest.mark.asyncio
async def test_scraper_normalize(
    test_settings: Settings,
    sample_hn_html: str,
) -> None:
    """Test mapping from RawScrapedItem to canonical NormalizedRecord models."""
    scraper = WebScraper(settings=test_settings)
    raw_items = scraper._parse_dom(sample_hn_html)

    records = scraper.normalize(raw_items)

    assert len(records) == len(raw_items)
    for rec in records:
        assert rec.source == "web_scraper_tech_news"
        assert rec.source_type == SourceType.WEB_SCRAPER
        assert rec.category == "tech_news"
        assert rec.id.isalnum()
        assert rec.checksum.isalnum()
        assert "score" in rec.payload
        assert "author" in rec.payload


@pytest.mark.asyncio
async def test_scraper_http_fetch_with_custom_user_agent(
    test_settings: Settings,
    sample_hn_html: str,
) -> None:
    """Verify that scraper issues requests with custom configured User-Agent."""
    scraper = WebScraper(settings=test_settings)
    target_url = scraper.target_url

    with respx.mock:
        route = respx.get(target_url).respond(status_code=200, html=sample_hn_html)
        items = await scraper.extract()

    assert route.called
    sent_request = route.calls[0].request
    assert test_settings.SCRAPER_USER_AGENT in sent_request.headers["user-agent"]
    assert len(items) == 2


@pytest.mark.asyncio
async def test_scraper_retry_and_fallback_on_network_failure(
    test_settings: Settings,
) -> None:
    """Verify scraper retries on network error and returns synthetic fallback DOM."""
    scraper = WebScraper(settings=test_settings)
    target_url = scraper.target_url

    with respx.mock:
        route = respx.get(target_url)
        route.side_effect = httpx.ConnectError("Connection refused by host")

        items = await scraper.extract()

    assert route.call_count == test_settings.HTTP_MAX_RETRIES
    # Fallback HTML should have been parsed
    assert len(items) >= 2
    assert any("Enterprise Data Gateway" in item.title for item in items)

