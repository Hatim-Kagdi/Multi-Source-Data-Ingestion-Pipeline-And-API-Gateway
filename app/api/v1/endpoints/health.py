"""System health check and dependency probing endpoint."""

from datetime import datetime, timezone
from fastapi import APIRouter, status
from app.core.config import get_settings
from app.core.redis import RedisManager
from app.schemas.normalized_data import HealthResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Service and Dependency Health Probe",
    description="Checks operational health of the FastAPI gateway and tests Async Redis cache latency.",
)
async def check_health() -> HealthResponse:
    """Probe gateway status and measure Redis connectivity round-trip latency."""
    settings = get_settings()
    is_connected, latency_ms = await RedisManager.ping()

    overall_status = "healthy" if is_connected else "degraded"

    return HealthResponse(
        status=overall_status,
        app_version=settings.VERSION,
        environment=settings.ENVIRONMENT,
        redis_connected=is_connected,
        redis_latency_ms=latency_ms,
        timestamp=datetime.now(timezone.utc),
    )

