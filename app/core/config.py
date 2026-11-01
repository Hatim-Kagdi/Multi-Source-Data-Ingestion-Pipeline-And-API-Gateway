"""Application configuration settings module.

Loads environment variables using Pydantic Settings (v2) with validation,
defaults, and type enforcement.
"""

from functools import lru_cache
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application runtime settings and configuration parameters."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application Metadata
    PROJECT_NAME: str = Field(
        default="Enterprise Data Gateway",
        description="The display name of the application service",
    )
    VERSION: str = Field(
        default="1.0.0",
        description="Application semantic version",
    )
    API_V1_STR: str = Field(
        default="/api/v1",
        description="Base routing prefix for API version 1",
    )
    ENVIRONMENT: Literal["development", "staging", "production", "testing"] = Field(
        default="development",
        description="Deployment runtime environment",
    )
    DEBUG: bool = Field(
        default=False,
        description="Debug mode toggle for verbose traces",
    )
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Root logging severity level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )

    # Server Binding
    HOST: str = Field(
        default="0.0.0.0",
        description="Host interface to bind server listener",
    )
    PORT: int = Field(
        default=8000,
        description="Port number to bind server listener",
    )
    WORKERS: int = Field(
        default=1,
        description="Number of Uvicorn worker processes",
    )

    # Redis Cache Configuration
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Full connection URI for Redis server",
    )
    REDIS_CACHE_TTL_SECONDS: int = Field(
        default=300,
        description="Default expiration time for cached dataset records (seconds)",
    )
    REDIS_SOCKET_TIMEOUT: float = Field(
        default=5.0,
        description="Socket timeout for Redis operations in seconds",
    )
    REDIS_MAX_CONNECTIONS: int = Field(
        default=10,
        description="Maximum concurrent connections in Redis connection pool",
    )

    # External Data Sources
    EXTERNAL_API_BASE_URL: str = Field(
        default="https://api.frankfurter.app",
        description="Base URL for target external JSON REST API",
    )
    SCRAPING_TARGET_URL: str = Field(
        default="https://news.ycombinator.com",
        description="Target web page URL for HTML DOM extraction",
    )

    # Network Resilience & Retry Policies
    HTTP_TIMEOUT_SECONDS: float = Field(
        default=10.0,
        description="Max request timeout for outbound HTTP calls in seconds",
    )
    HTTP_MAX_RETRIES: int = Field(
        default=3,
        description="Maximum retry attempts on transient network or server errors",
    )
    HTTP_BACKOFF_FACTOR: float = Field(
        default=0.5,
        description="Multiplier factor for exponential backoff delay calculation",
    )
    SCRAPER_USER_AGENT: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36 DataGateway/1.0"
        ),
        description="Custom User-Agent header string sent during scraping",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton instance of runtime application settings."""
    return Settings()

