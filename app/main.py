"""FastAPI Application Entry Point.

Initializes the API gateway, attaches lifespan lifecycle handlers for Redis connection
pooling, registers middleware, configures exception handlers, and mounts API routers.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.redis import RedisManager

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager for startup and shutdown hooks."""
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL)
    logger.info(f"=== Starting {settings.PROJECT_NAME} (v{settings.VERSION}) ===")
    logger.info(f"Environment: {settings.ENVIRONMENT} | Debug: {settings.DEBUG}")

    # Initialize Redis connection pool
    try:
        RedisManager.init_pool()
        connected, latency = await RedisManager.ping()
        if connected:
            logger.info(f"Connected to Redis cache backend successfully (latency: {latency}ms)")
        else:
            logger.warning(
                "Redis connection failed during startup; continuing in degraded cache-bypass mode"
            )
    except Exception as exc:
        logger.warning(f"Could not connect to Redis during startup: {exc}")

    yield

    # Shutdown: Cleanly close Redis connections
    logger.info("=== Shutting down Data Gateway: cleaning up active connections ===")
    try:
        await RedisManager.close_pool()
    except Exception as exc:
        logger.error(f"Error disconnecting Redis on shutdown: {exc}")


def create_application() -> FastAPI:
    """Factory creating and configuring the primary FastAPI application instance."""
    settings = get_settings()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description=(
            "Enterprise-grade multi-source asynchronous data ingestion pipeline "
            "and Redis-backed API gateway with automated fallback recovery."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Cross-Origin Resource Sharing (CORS) Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register custom domain exception handlers
    register_exception_handlers(app)

    # Mount API routers
    app.include_router(api_router, prefix=settings.API_V1_STR)

    @app.get(
        "/",
        tags=["System Information"],
        summary="Service Root Status",
        description="Returns service metadata and interactive documentation links.",
    )
    async def root() -> JSONResponse:
        return JSONResponse(
            content={
                "service": settings.PROJECT_NAME,
                "version": settings.VERSION,
                "status": "operational",
                "documentation": {
                    "swagger_ui": "/docs",
                    "redoc": "/redoc",
                    "openapi_schema": "/openapi.json",
                },
                "endpoints": {
                    "health": f"{settings.API_V1_STR}/health",
                    "ingest_trigger": f"{settings.API_V1_STR}/ingest/trigger",
                    "aggregated_data": f"{settings.API_V1_STR}/data/aggregated",
                },
            }
        )

    return app


app = create_application()


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        workers=settings.WORKERS,
    )

