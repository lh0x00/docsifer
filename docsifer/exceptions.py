"""Domain-level exception hierarchy mapped to HTTP status codes.

Endpoints raise ``DocsiferError`` subclasses; the global exception handler
converts them into JSON responses with sanitized messages so internal stack
traces never leak to clients.
"""

from __future__ import annotations

from typing import Any


class DocsiferError(Exception):
    """Base class for all application-level errors."""

    status_code: int = 500
    public_message: str = "Internal server error"

    def __init__(
        self,
        message: str | None = None,
        *,
        public_message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or self.public_message)
        self.details = details or {}
        if public_message is not None:
            self.public_message = public_message


# ---------------------------------------------------------------------------
# 4xx — client errors
# ---------------------------------------------------------------------------
class InvalidInputError(DocsiferError):
    status_code = 400
    public_message = "Invalid input"


class UnauthorizedError(DocsiferError):
    status_code = 401
    public_message = "Unauthorized"


class ForbiddenError(DocsiferError):
    status_code = 403
    public_message = "Forbidden"


class NotFoundError(DocsiferError):
    status_code = 404
    public_message = "Resource not found"


class PayloadTooLargeError(DocsiferError):
    status_code = 413
    public_message = "Payload too large"


class UnsupportedFormatError(DocsiferError):
    status_code = 415
    public_message = "Unsupported file format"


class ValidationError(DocsiferError):
    status_code = 422
    public_message = "Validation failed"


class TooManyRequestsError(DocsiferError):
    status_code = 429
    public_message = "Too many requests"


# ---------------------------------------------------------------------------
# 5xx — server errors
# ---------------------------------------------------------------------------
class ConversionFailedError(DocsiferError):
    status_code = 500
    public_message = "Conversion failed"


class UpstreamLLMError(DocsiferError):
    status_code = 502
    public_message = "Upstream LLM error"


class ServiceUnavailableError(DocsiferError):
    status_code = 503
    public_message = "Service unavailable"


class ResourceExhaustedError(ServiceUnavailableError):
    public_message = "Server resources are exhausted, please retry later"


class CircuitOpenError(ServiceUnavailableError):
    public_message = "Upstream temporarily unavailable"


class QueueFullError(ServiceUnavailableError):
    public_message = "Server is busy, please retry later"


class GatewayTimeoutError(DocsiferError):
    status_code = 504
    public_message = "Upstream timeout"
