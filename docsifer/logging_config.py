"""Logging setup with optional structured JSON output and request-id binding.

Call :func:`configure_logging` exactly once at application start (inside the
FastAPI lifespan).
"""

from __future__ import annotations

import json
import logging
import logging.config
import sys
from contextvars import ContextVar
from typing import Any

#: Context variable carrying the current request id for the active task.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIdFilter(logging.Filter):
    """Inject the current request id (if any) into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """Minimal JSON formatter producing a single line per record."""

    _RESERVED = {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Allow callers to attach extra fields via ``logger.info("...", extra={...})``.
        for key, value in record.__dict__.items():
            if key in self._RESERVED or key.startswith("_") or key == "request_id":
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    """Configure the root logger and library loggers in one place.

    Args:
        level: Log level name (``DEBUG``/``INFO``/...).
        json_output: When ``True`` emit one JSON object per line; otherwise use
            a human-readable format (useful in local development).
    """
    formatter: dict[str, Any]
    if json_output:
        formatter = {"()": "docsifer.logging_config.JsonFormatter"}
    else:
        formatter = {
            "format": "%(asctime)s %(levelname)-8s %(name)s [%(request_id)s] %(message)s",
            "datefmt": "%H:%M:%S",
        }

    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_id": {"()": "docsifer.logging_config.RequestIdFilter"},
        },
        "formatters": {"default": formatter},
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
                "formatter": "default",
                "filters": ["request_id"],
            }
        },
        "loggers": {
            "": {"handlers": ["default"], "level": level, "propagate": False},
            "uvicorn": {"handlers": ["default"], "level": level, "propagate": False},
            "uvicorn.error": {"handlers": ["default"], "level": level, "propagate": False},
            "uvicorn.access": {"handlers": ["default"], "level": level, "propagate": False},
            "gunicorn.error": {"handlers": ["default"], "level": level, "propagate": False},
            "gunicorn.access": {"handlers": ["default"], "level": level, "propagate": False},
        },
    }

    logging.config.dictConfig(config)
