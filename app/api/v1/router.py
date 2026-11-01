"""API v1 master router module.

Consolidates all v1 endpoint routers (ingestion trigger, aggregated data query,
health monitoring) under the unified /api/v1 namespace.
"""

from fastapi import APIRouter
from app.api.v1.endpoints import aggregator, health, ingestion

api_router = APIRouter()

# Mount endpoints
api_router.include_router(
    ingestion.router,
    prefix="/ingest",
    tags=["Ingestion Engine"],
)
api_router.include_router(
    aggregator.router,
    prefix="/data",
    tags=["Data Aggregator & Cache"],
)
api_router.include_router(
    health.router,
    tags=["System Health"],
)

