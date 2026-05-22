"""Custom middleware: request id, body size limit, security headers."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from ..config import Settings
from ..logging_config import request_id_var

ASGICall = Callable[[Request], Awaitable[Response]]

REQUEST_ID_HEADER = "X-Request-ID"
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    # Allow huggingface.co to embed the Space in its hub iframe while still
    # blocking arbitrary third-party framing. ``frame-ancestors`` supersedes
    # the legacy ``X-Frame-Options`` header (which has no allowlist mode).
    "Content-Security-Policy": (
        "frame-ancestors 'self' https://huggingface.co https://*.huggingface.co "
        "https://*.hf.space"
    ),
    "Referrer-Policy": "no-referrer",
    "X-XSS-Protection": "0",
}


async def _request_id_middleware(request: Request, call_next: ASGICall) -> Response:
    rid = request.headers.get(REQUEST_ID_HEADER) or secrets.token_hex(8)
    token = request_id_var.set(rid)
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers[REQUEST_ID_HEADER] = rid
    return response


def _make_body_limit_middleware(
    max_bytes: int,
) -> Callable[[Request, ASGICall], Awaitable[Response]]:
    async def _body_limit(request: Request, call_next: ASGICall) -> Response:
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                content_length = int(cl)
            except ValueError:
                content_length = None
            if content_length is not None and content_length > max_bytes:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": "PayloadTooLargeError",
                        "message": "Payload too large",
                        "details": {"max_bytes": max_bytes},
                        "request_id": request_id_var.get(),
                    },
                )
        return await call_next(request)

    return _body_limit


async def _security_headers_middleware(request: Request, call_next: ASGICall) -> Response:
    response = await call_next(request)
    for header, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    return response


def register_middleware(app: FastAPI, settings: Settings) -> None:
    """Wire middleware in the correct order.

    Order (outermost first): request-id → body-limit → security-headers.
    Starlette executes them in *registration* order on the way in and reverse
    order on the way out, so the first one we add runs outermost.
    """
    app.middleware("http")(_request_id_middleware)
    app.middleware("http")(_make_body_limit_middleware(settings.max_upload_bytes))
    if settings.enable_security_headers:
        app.middleware("http")(_security_headers_middleware)
