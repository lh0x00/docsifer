"""Usage statistics endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...analytics import AnalyticsService
from ..deps import analytics_dep
from ..schemas import StatsResponse

router = APIRouter(tags=["v1"])


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Get usage statistics",
)
async def get_stats(
    analytics: AnalyticsService = Depends(analytics_dep),
) -> StatsResponse:
    snap = await analytics.stats()
    return StatsResponse(
        access=snap.get("access", {}),
        tokens=snap.get("tokens", {}),
        healthy=bool(snap.get("healthy", True)),
    )
