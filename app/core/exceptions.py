"""Custom exception hierarchy and FastAPI exception handlers.

Provides structured error models and domain-specific exceptions for network,
scraping, parsing, and caching failure modes.
"""

from typing import Any, Dict, Optional
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from app.core.logging import get_logger

logger = get_logger(__name__)


# ------------------------------------------------------------------------------
# Domain-Specific Exception Hierarchy
# ------------------------------------------------------------------------------

class DataGatewayException(Exception):
    """Root exception for all domain errors within Data Gateway."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_GATEWAY_ERROR",
        details: Optional[Dict[str, Any]] = None,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}
        self.status_code = status_code


class IngestionException(DataGatewayException):
    """Raised when an ingestion task fails completely."""

    def __init__(
        self,
        message: str,
        source: str = "unknown",
        code: str = "INGESTION_ERROR",
        details: Optional[Dict[str, Any]] = None,
        status_code: int = status.HTTP_502_BAD_GATEWAY,
    ) -> None:
        details = details or {}
        details["source"] = source
        super().__init__(
            message=message,
            code=code,
            details=details,
            status_code=status_code,
        )
        self.source = source


class APIClientException(IngestionException):
    """Raised on external REST API HTTP/connection failures."""

    def __init__(
        self,
        message: str,
        url: str,
        http_status: Optional[int] = None,
        code: str = "API_CLIENT_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        details = details or {}
        details.update({"url": url, "http_status": http_status})
        super().__init__(
            message=message,
            source="external_api",
            code=code,
            details=details,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
        self.url = url
        self.http_status = http_status


class RateLimitException(APIClientException):
    """Raised when an external API service returns HTTP 429 Too Many Requests."""

    def __init__(
        self,
        message: str = "Third-party API rate limit exceeded",
        url: str = "",
        retry_after: Optional[int] = None,
    ) -> None:
        details = {"retry_after": retry_after} if retry_after else {}
        super().__init__(
            message=message,
            url=url,
            http_status=status.HTTP_429_TOO_MANY_REQUESTS,
            code="EXTERNAL_RATE_LIMIT_EXCEEDED",
            details=details,
        )
        self.status_code = status.HTTP_429_TOO_MANY_REQUESTS


class ScraperException(IngestionException):
    """Raised when scraping target web page fails due to network or HTTP errors."""

    def __init__(
        self,
        message: str,
        url: str,
        http_status: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        details = details or {}
        details.update({"url": url, "http_status": http_status})
        super().__init__(
            message=message,
            source="web_scraper",
            code="SCRAPER_FETCH_ERROR",
            details=details,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )


class ParserException(IngestionException):
    """Raised when HTML parsing or DOM extraction fails unrecoverably."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            source="dom_parser",
            code="DOM_PARSER_ERROR",
            details=details,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


class CacheException(DataGatewayException):
    """Raised when Redis caching operations fail."""

    def __init__(
        self,
        message: str,
        operation: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        details = details or {}
        details["operation"] = operation
        super().__init__(
            message=message,
            code="CACHE_ERROR",
            details=details,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class ResourceNotFoundException(DataGatewayException):
    """Raised when requested dataset or source cannot be located."""

    def __init__(
        self,
        message: str = "Requested resource not found",
        resource_id: Optional[str] = None,
    ) -> None:
        details = {"resource_id": resource_id} if resource_id else {}
        super().__init__(
            message=message,
            code="RESOURCE_NOT_FOUND",
            details=details,
            status_code=status.HTTP_404_NOT_FOUND,
        )


# ------------------------------------------------------------------------------
# FastAPI Exception Handler Registration
# ------------------------------------------------------------------------------

def register_exception_handlers(app: FastAPI) -> None:
    """Register custom exception handlers with FastAPI application."""

    @app.exception_handler(DataGatewayException)
    async def gateway_exception_handler(
        request: Request,
        exc: DataGatewayException,
    ) -> JSONResponse:
        logger.error(
            f"Gateway exception caught on {request.method} {request.url.path}: "
            f"[{exc.code}] {exc.message} - Details: {exc.details}"
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "path": request.url.path,
                },
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.exception(
            f"Unhandled system error on {request.method} {request.url.path}: {str(exc)}"
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected error occurred processing your request.",
                    "details": {"error_type": type(exc).__name__},
                    "path": request.url.path,
                },
            },
        )

