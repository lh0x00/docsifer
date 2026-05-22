"""Health probes (liveness + readiness) for orchestration platforms."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...analytics import AnalyticsService
from ...config import Settings
from ..deps import analytics_dep, settings_dep
from ..schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get(
    "/healthz",
    response_model=HealthResponse,
    summary="Liveness probe",
    description="Always returns 200 if the process is responsive.",
)
async def healthz(settings: Settings = Depends(settings_dep)) -> HealthResponse:
    return HealthResponse(status="ok", version=settings.app_version)


@router.get(
    "/readyz",
    response_model=HealthResponse,
    summary="Readiness probe",
    description="Returns 200 only when the analytics backend is reachable.",
)
async def readyz(
    analytics: AnalyticsService = Depends(analytics_dep),
    settings: Settings = Depends(settings_dep),
) -> HealthResponse:
    healthy = await analytics.ping() if settings.analytics_persistent else True
    if not healthy:
        return HealthResponse(
            status="degraded",
            version=settings.app_version,
            details={"analytics": "unreachable"},
        )
    return HealthResponse(status="ready", version=settings.app_version)
