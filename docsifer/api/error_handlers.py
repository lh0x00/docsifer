"""Translate domain and unexpected exceptions into safe JSON responses."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..exceptions import DocsiferError
from ..logging_config import request_id_var

logger = logging.getLogger(__name__)


def _payload(
    *,
    error: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "error": error,
        "message": message,
        "request_id": request_id_var.get(),
    }
    if details:
        body["details"] = details
    return body


async def _docsifer_handler(request: Request, exc: DocsiferError) -> JSONResponse:
    log = logger.warning if exc.status_code < 500 else logger.exception
    log(
        "%s on %s: %s",
        exc.__class__.__name__,
        request.url.path,
        exc,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=_payload(
            error=exc.__class__.__name__,
            message=exc.public_message,
            details=exc.details or None,
        ),
    )


async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_payload(
            error="HTTPException",
            message=str(exc.detail) if exc.detail else "HTTP error",
        ),
    )


async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=_payload(
            error="ValidationError",
            message="Request validation failed",
            details={"errors": exc.errors()},
        ),
    )


async def _fallback_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content=_payload(
            error="InternalServerError",
            message="An unexpected error occurred",
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DocsiferError, _docsifer_handler)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _fallback_handler)
