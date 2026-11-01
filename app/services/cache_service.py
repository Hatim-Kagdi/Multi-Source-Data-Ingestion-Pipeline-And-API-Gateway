"""Async Redis Caching Service.

Provides type-safe caching operations with TTL expiry, JSON serialization,
and resilient error handling to prevent API disruption if Redis becomes unreachable.
"""

import json
from typing import Any, List, Optional
import redis.asyncio as aioredis
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.redis import RedisManager
from app.schemas.normalized_data import NormalizedRecord

logger = get_logger(__name__)


class CacheService:
    """Manages reading, writing, and invalidating cached datasets in Redis."""

    def __init__(
        self,
        redis_client: Optional[aioredis.Redis] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = redis_client

    def _get_client(self) -> aioredis.Redis:
        """Return injected Redis client or connection from RedisManager."""
        if self._client is not None:
            return self._client
        return RedisManager.get_client()

    async def get(self, key: str) -> Optional[str]:
        """Retrieve raw string value from cache."""
        try:
            client = self._get_client()
            return await client.get(key)
        except Exception as exc:
            logger.warning(f"[CacheService] Redis GET error for key '{key}': {exc}")
            return None

    async def set(
        self,
        key: str,
        value: str,
        ttl: Optional[int] = None,
    ) -> bool:
        """Store string value in cache with optional TTL in seconds."""
        effective_ttl = ttl if ttl is not None else self.settings.REDIS_CACHE_TTL_SECONDS
        try:
            client = self._get_client()
            await client.set(key, value, ex=effective_ttl)
            logger.debug(f"[CacheService] Cached key '{key}' with TTL {effective_ttl}s")
            return True
        except Exception as exc:
            logger.warning(f"[CacheService] Redis SET error for key '{key}': {exc}")
            return False

    async def get_json(self, key: str) -> Optional[Any]:
        """Retrieve and deserialize JSON data from cache."""
        raw = await self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError) as decode_err:
            logger.error(f"[CacheService] Failed to decode JSON for key '{key}': {decode_err}")
            return None

    async def set_json(
        self,
        key: str,
        data: Any,
        ttl: Optional[int] = None,
    ) -> bool:
        """Serialize data to JSON and store with TTL in seconds."""
        try:
            serialized = json.dumps(data, default=str)
            return await self.set(key, serialized, ttl=ttl)
        except (TypeError, ValueError) as encode_err:
            logger.error(f"[CacheService] Failed to serialize JSON for key '{key}': {encode_err}")
            return False

    async def get_normalized_records(self, key: str) -> Optional[List[NormalizedRecord]]:
        """Retrieve and validate a list of NormalizedRecord models from cache."""
        data = await self.get_json(key)
        if data is None:
            logger.info(f"[CacheService] Cache MISS for key '{key}'")
            return None
        try:
            logger.info(f"[CacheService] Cache HIT for key '{key}' ({len(data)} items)")
            return [NormalizedRecord.model_validate(item) for item in data]
        except Exception as val_err:
            logger.error(f"[CacheService] Failed to validate cached NormalizedRecord: {val_err}")
            return None

    async def set_normalized_records(
        self,
        key: str,
        records: List[NormalizedRecord],
        ttl: Optional[int] = None,
    ) -> bool:
        """Serialize and cache a list of NormalizedRecord models."""
        serialized_list = [record.model_dump(mode="json") for record in records]
        return await self.set_json(key, serialized_list, ttl=ttl)

    async def ttl(self, key: str) -> int:
        """Get remaining TTL in seconds for a given key."""
        try:
            client = self._get_client()
            return await client.ttl(key)
        except Exception as exc:
            logger.warning(f"[CacheService] Redis TTL check error for key '{key}': {exc}")
            return -1

    async def exists(self, key: str) -> bool:
        """Check if a given cache key exists."""
        try:
            client = self._get_client()
            return bool(await client.exists(key))
        except Exception as exc:
            logger.warning(f"[CacheService] Redis EXISTS error for key '{key}': {exc}")
            return False

    async def delete(self, key: str) -> bool:
        """Remove a specific key from cache."""
        try:
            client = self._get_client()
            await client.delete(key)
            return True
        except Exception as exc:
            logger.warning(f"[CacheService] Redis DELETE error for key '{key}': {exc}")
            return False

