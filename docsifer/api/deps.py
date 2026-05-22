"""FastAPI dependency providers wired against the app state."""

from __future__ import annotations

from fastapi import Depends, Request

from ..analytics import AnalyticsService
from ..config import Settings, get_settings
from ..core.service import DocsiferService
from ..safety import ConversionGate, PerIPLimiter, ResourceGuard


def settings_dep() -> Settings:
    return get_settings()


def converter_dep(request: Request) -> DocsiferService:
    return request.app.state.converter  # type: ignore[no-any-return]


def analytics_dep(request: Request) -> AnalyticsService:
    return request.app.state.analytics  # type: ignore[no-any-return]


def conversion_gate_dep(request: Request) -> ConversionGate:
    return request.app.state.conversion_gate  # type: ignore[no-any-return]


def per_ip_limiter_dep(request: Request) -> PerIPLimiter:
    return request.app.state.per_ip_limiter  # type: ignore[no-any-return]


def resource_guard_dep(request: Request) -> ResourceGuard:
    return request.app.state.resource_guard  # type: ignore[no-any-return]


def client_ip_dep(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else "unknown"


__all__ = [
    "Depends",
    "analytics_dep",
    "client_ip_dep",
    "conversion_gate_dep",
    "converter_dep",
    "per_ip_limiter_dep",
    "resource_guard_dep",
    "settings_dep",
]
