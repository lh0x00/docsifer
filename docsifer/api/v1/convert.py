"""``POST /v1/convert`` endpoint.

Implements all the safety controls from Section N (admission, per-IP
fairness, resource guard) plus the bug fixes from Section A:

- A3 path-traversal: filename is sanitized via ``Path(name).name``.
- A4 SSRF: URLs are validated by :func:`validate_url`.
- F4 body size: enforced by middleware.
- F5 MIME allowlist: enforced here against ``settings.allowed_extensions``.
- F6 leak: errors mapped to :class:`DocsiferError` subclasses.
- C6 blocking I/O: file is streamed to disk in a worker thread.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from fastapi.responses import ORJSONResponse

from ...analytics import AnalyticsService
from ...config import Settings
from ...core.service import DocsiferService
from ...core.url_guard import validate_url
from ...exceptions import (
    InvalidInputError,
    PayloadTooLargeError,
    UnsupportedFormatError,
    ValidationError,
)
from ...safety import ConversionGate, PerIPLimiter, ResourceGuard
from ..deps import (
    analytics_dep,
    client_ip_dep,
    conversion_gate_dep,
    converter_dep,
    per_ip_limiter_dep,
    resource_guard_dep,
    settings_dep,
)
from ..schemas import ConvertResponse, ConvertSettings, HTTPConfig, OpenAIConfig

logger = logging.getLogger(__name__)
router = APIRouter(tags=["v1"])

_CHUNK_SIZE = 1024 * 1024  # 1 MB


def _parse_json_form(name: str, raw: str | None, model: type[Any]) -> Any:
    if not raw or not raw.strip():
        return model()
    try:
        return model.model_validate_json(raw)
    except Exception as exc:
        raise ValidationError(
            f"Invalid JSON in '{name}'",
            details={"field": name, "error": str(exc)},
        ) from exc


def _safe_filename(raw: str | None) -> str:
    name = (raw or "").strip()
    safe = Path(name).name if name else ""
    return safe or f"upload-{secrets.token_hex(4)}.bin"


def _check_extension(name: str, allowed: set[str]) -> None:
    suffix = Path(name).suffix.lower()
    if not suffix:
        return  # allow extensionless and rely on MIME sniff
    if suffix not in allowed:
        raise UnsupportedFormatError(
            f"Extension '{suffix}' is not allowed",
            details={"allowed": sorted(allowed)},
        )


async def _stream_to_disk(
    upload: UploadFile,
    dst: Path,
    *,
    max_bytes: int,
) -> int:
    """Stream the upload to ``dst`` without loading it fully into RAM."""

    def _copy() -> int:
        total = 0
        with dst.open("wb") as fh:
            while True:
                chunk = upload.file.read(_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise PayloadTooLargeError(
                        f"Body exceeds {max_bytes} bytes",
                        details={"max_bytes": max_bytes},
                    )
                fh.write(chunk)
        return total

    try:
        return await asyncio.to_thread(_copy)
    finally:
        await upload.close()


@router.post(
    "/convert",
    response_model=ConvertResponse,
    response_class=ORJSONResponse,
    summary="Convert a file or URL into Markdown",
    responses={
        400: {"description": "Invalid input"},
        413: {"description": "Payload too large"},
        415: {"description": "Unsupported format"},
        422: {"description": "Validation failed"},
        429: {"description": "Too many requests"},
        503: {"description": "Service unavailable"},
    },
)
async def convert_document(
    background_tasks: BackgroundTasks,
    file: UploadFile | None = File(default=None, description="File to convert"),
    url: str | None = Form(default=None, description="URL to convert"),
    openai: str | None = Form(default=None, description="OpenAI config JSON"),
    http: str | None = Form(default=None, description="HTTP config JSON"),
    settings_form: str | None = Form(default=None, alias="settings"),
    settings: Settings = Depends(settings_dep),
    converter: DocsiferService = Depends(converter_dep),
    analytics: AnalyticsService = Depends(analytics_dep),
    gate: ConversionGate = Depends(conversion_gate_dep),
    per_ip: PerIPLimiter = Depends(per_ip_limiter_dep),
    guard: ResourceGuard = Depends(resource_guard_dep),
    client_ip: str = Depends(client_ip_dep),
) -> ConvertResponse:
    if file is None and not (url and url.strip()):
        raise InvalidInputError("Provide either 'file' or 'url'.")

    openai_cfg = _parse_json_form("openai", openai, OpenAIConfig)
    http_cfg = _parse_json_form("http", http, HTTPConfig)
    convert_cfg = _parse_json_form("settings", settings_form, ConvertSettings)

    async with per_ip.acquire(client_ip):
        async with gate.acquire():
            if file is not None:
                guard.check(0)  # file size unknown until streamed
                _check_extension(file.filename or "", set(settings.allowed_extensions))

                tmp_root = Path(tempfile.mkdtemp(prefix="docsifer-", dir=settings.tmp_dir))
                try:
                    safe_name = _safe_filename(file.filename)
                    dst = tmp_root / safe_name
                    size = await _stream_to_disk(
                        file, dst, max_bytes=settings.max_upload_bytes
                    )
                    logger.info(
                        "Convert file received",
                        extra={
                            "filename": safe_name,
                            "size": size,
                            "client_ip": client_ip,
                        },
                    )
                    guard.check(size)

                    result = await asyncio.wait_for(
                        converter.convert_file(
                            dst,
                            openai_config=openai_cfg.to_dict(),
                            http_config=http_cfg.to_dict(),
                            cleanup_html=convert_cfg.cleanup,
                        ),
                        timeout=settings.request_timeout_sec,
                    )
                finally:
                    shutil.rmtree(tmp_root, ignore_errors=True)
            else:
                safe_url = validate_url(
                    url or "",
                    allowed_schemes=settings.url_allowed_schemes,
                    allow_private_networks=settings.url_allow_private_networks,
                )
                logger.info(
                    "Convert URL received",
                    extra={"url": safe_url, "client_ip": client_ip},
                )
                guard.check(0)
                result = await asyncio.wait_for(
                    converter.convert_file(
                        safe_url,
                        openai_config=openai_cfg.to_dict(),
                        http_config=http_cfg.to_dict(),
                        cleanup_html=convert_cfg.cleanup,
                    ),
                    timeout=settings.request_timeout_sec,
                )

    background_tasks.add_task(_record_access_safe, analytics, result.token_count)
    return ConvertResponse(filename=result.filename, markdown=result.markdown)


async def _record_access_safe(analytics: AnalyticsService, tokens: int) -> None:
    try:
        await analytics.access(tokens)
    except Exception:
        logger.exception("Failed to record analytics access")
