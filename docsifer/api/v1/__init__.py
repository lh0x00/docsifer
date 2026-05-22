"""v1 API routers."""

from fastapi import APIRouter

from .convert import router as convert_router
from .health import router as health_router
from .stats import router as stats_router

router = APIRouter()
router.include_router(convert_router)
router.include_router(stats_router)
router.include_router(health_router)

__all__ = ["router"]
