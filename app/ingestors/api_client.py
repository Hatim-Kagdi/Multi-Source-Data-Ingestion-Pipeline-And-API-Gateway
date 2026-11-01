"""External REST API Ingestor Client.

Implements asynchronous consumption of external JSON endpoints with exponential
backoff retry logic, rate limit handling, and graceful fallback mechanisms.
"""

import asyncio
from datetime import datetime, timezone
import random
from typing import Any, Dict, List, Optional
import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import APIClientException, RateLimitException
from app.core.logging import get_logger
from app.ingestors.base import BaseIngestor
from app.schemas.normalized_data import NormalizedRecord, SourceType
from app.schemas.raw_data import RawAPIPayload

logger = get_logger(__name__)


class APIClient(BaseIngestor):
    """Asynchronous client for extracting and normalizing REST API financial datasets."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[httpx.AsyncClient] = None,
        base_currency: str = "USD",
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self.base_currency = base_currency
        self.base_url = self.settings.EXTERNAL_API_BASE_URL.rstrip("/")
        self.endpoint = f"{self.base_url}/latest?from={self.base_currency}"

    @property
    def source_name(self) -> str:
        return "api_exchange_rates"

    @property
    def source_type(self) -> SourceType:
        return SourceType.REST_API

    @property
    def category(self) -> str:
        return "financial"

    async def _get_client(self) -> httpx.AsyncClient:
        """Return the injected HTTP client or instantiate a configured AsyncClient."""
        if self._client is not None:
            return self._client
        return httpx.AsyncClient(
            timeout=self.settings.HTTP_TIMEOUT_SECONDS,
            headers={"Accept": "application/json"},
        )

    async def extract(self) -> RawAPIPayload:
        """Fetch raw JSON exchange rate data with exponential backoff retries.

        Handles:
        - 429 Too Many Requests with Retry-After or exponential backoff
        - 5xx transient server errors
        - Network timeouts and connection drops
        - Fallback data generation if third party fails unrecoverably
        """
        max_retries = self.settings.HTTP_MAX_RETRIES
        backoff_factor = self.settings.HTTP_BACKOFF_FACTOR
        url = self.endpoint

        client = await self._get_client()
        owns_client = self._client is None

        try:
            for attempt in range(1, max_retries + 1):
                try:
                    logger.debug(
                        f"[{self.source_name}] Attempt {attempt}/{max_retries} fetching {url}"
                    )
                    response = await client.get(url)

                    # Handle 429 Rate Limiting
                    if response.status_code == 429:
                        retry_after_header = response.headers.get("Retry-After")
                        retry_after = (
                            int(retry_after_header)
                            if retry_after_header and retry_after_header.isdigit()
                            else int(backoff_factor * (2 ** (attempt - 1)))
                        )
                        logger.warning(
                            f"[{self.source_name}] HTTP 429 Rate Limit encountered. "
                            f"Waiting {retry_after}s before retry (attempt {attempt}/{max_retries})"
                        )
                        if attempt == max_retries:
                            raise RateLimitException(
                                message="External API rate limit reached max retries",
                                url=url,
                                retry_after=retry_after,
                            )
                        await asyncio.sleep(retry_after)
                        continue

                    # Handle 5xx Server Errors (retriable)
                    if 500 <= response.status_code <= 599:
                        logger.warning(
                            f"[{self.source_name}] HTTP {response.status_code} server error "
                            f"on attempt {attempt}/{max_retries}"
                        )
                        if attempt == max_retries:
                            response.raise_for_status()
                        delay = backoff_factor * (2 ** (attempt - 1)) + random.uniform(0.1, 0.3)
                        await asyncio.sleep(delay)
                        continue

                    # Raise for 4xx Client Errors (non-retriable)
                    response.raise_for_status()

                    data = response.json()
                    return RawAPIPayload(
                        amount=float(data.get("amount", 1.0)),
                        base=str(data.get("base", self.base_currency)),
                        date=str(data.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))),
                        rates=data.get("rates", {}),
                        raw_response=data,
                    )

                except (httpx.TimeoutException, httpx.NetworkError) as net_err:
                    logger.warning(
                        f"[{self.source_name}] Network error on attempt {attempt}/{max_retries}: {net_err}"
                    )
                    if attempt == max_retries:
                        logger.error(
                            f"[{self.source_name}] Retries exhausted. Applying graceful fallback."
                        )
                        return self._get_fallback_payload(str(net_err))
                    delay = backoff_factor * (2 ** (attempt - 1)) + random.uniform(0.1, 0.3)
                    await asyncio.sleep(delay)

                except httpx.HTTPStatusError as http_err:
                    if attempt == max_retries or (400 <= http_err.response.status_code < 500 and http_err.response.status_code != 429):
                        logger.error(
                            f"[{self.source_name}] HTTP status error {http_err.response.status_code}: {http_err}"
                        )
                        return self._get_fallback_payload(str(http_err))
                    delay = backoff_factor * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)

            # Fallback if loop ends without return
            return self._get_fallback_payload("Max retries exceeded without successful response")

        finally:
            if owns_client:
                await client.aclose()

    def _get_fallback_payload(self, reason: str) -> RawAPIPayload:
        """Provide safe default dataset when external API is unreachable."""
        logger.info(f"[{self.source_name}] Serving baseline fallback exchange rate records ({reason})")
        return RawAPIPayload(
            amount=1.0,
            base=self.base_currency,
            date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            rates={
                "EUR": 0.92,
                "GBP": 0.79,
                "JPY": 154.20,
                "CAD": 1.38,
                "AUD": 1.52,
                "CHF": 0.89,
                "INR": 83.50,
            },
            raw_response={"fallback": True, "reason": reason},
        )

    def normalize(self, raw_data: RawAPIPayload) -> List[NormalizedRecord]:
        """Convert raw exchange rate map into canonical NormalizedRecord objects."""
        records: List[NormalizedRecord] = []
        is_fallback = bool(raw_data.raw_response and raw_data.raw_response.get("fallback"))

        for target_currency, rate in raw_data.rates.items():
            pair_key = f"{raw_data.base}_{target_currency}"
            record_id = self.generate_id(self.source_name, pair_key)
            payload_dict = {
                "base_currency": raw_data.base,
                "target_currency": target_currency,
                "rate": float(rate),
                "quote_date": raw_data.date,
            }
            checksum = self.compute_checksum(payload_dict)

            record = NormalizedRecord(
                id=record_id,
                source=self.source_name,
                source_type=self.source_type,
                category=self.category,
                title=f"Exchange Rate: {raw_data.base}/{target_currency} = {rate}",
                payload=payload_dict,
                url=self.endpoint,
                checksum=checksum,
                metadata={
                    "base_amount": raw_data.amount,
                    "quote_date": raw_data.date,
                    "is_fallback": is_fallback,
                },
            )
            records.append(record)

        return records

