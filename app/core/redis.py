"""Async Redis connection manager module.

Manages connection pooling, lifecycle hooks, and health probing for the
application cache layer using redis-py's asyncio interface.
"""

import time
from typing import AsyncGenerator, Optional, Tuple
import redis.asyncio as aioredis
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class RedisManager:
    """Singleton manager for the asynchronous Redis connection pool."""

    _pool: Optional[aioredis.ConnectionPool] = None
    _client: Optional[aioredis.Redis] = None

    @classmethod
    def init_pool(cls) -> None:
        """Initialize the connection pool from application settings."""
        settings = get_settings()
        if cls._pool is None:
            logger.info(
                f"Initializing Async Redis connection pool at {settings.REDIS_URL} "
                f"(max_connections={settings.REDIS_MAX_CONNECTIONS})"
            )
            cls._pool = aioredis.ConnectionPool.from_url(
                settings.REDIS_URL,
                max_connections=settings.REDIS_MAX_CONNECTIONS,
                socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
                decode_responses=True,
            )
            cls._client = aioredis.Redis(connection_pool=cls._pool)

    @classmethod
    def set_client(cls, client: aioredis.Redis) -> None:
        """Directly inject a Redis client (useful for unit testing with fakeredis)."""
        cls._client = client

    @classmethod
    def get_client(cls) -> aioredis.Redis:
        """Return the active Redis client instance."""
        if cls._client is None:
            cls.init_pool()
        if cls._client is None:
            raise RuntimeError("Redis client failed to initialize")
        return cls._client

    @classmethod
    async def close_pool(cls) -> None:
        """Gracefully disconnect and close the Redis connection pool."""
        if cls._client is not None:
            logger.info("Closing Redis client connection...")
            await cls._client.aclose()
            cls._client = None
        if cls._pool is not None:
            logger.info("Disconnecting Redis connection pool...")
            await cls._pool.disconnect()
            cls._pool = None

    @classmethod
    async def ping(cls) -> Tuple[bool, Optional[float]]:
        """Ping the Redis server and measure round-trip latency in milliseconds."""
        client = cls.get_client()
        start = time.perf_counter()
        try:
            pong = await client.ping()
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            return bool(pong), latency_ms
        except Exception as exc:
            logger.warning(f"Redis ping check failed: {exc}")
            return False, None


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    """FastAPI dependency yielding an active Async Redis client."""
    client = RedisManager.get_client()
    try:
        yield client
    finally:
        pass

