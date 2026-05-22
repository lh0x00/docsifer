"""Token counting backed by ``tiktoken`` with a robust fallback chain."""

from __future__ import annotations

import logging
from typing import Protocol

import tiktoken

logger = logging.getLogger(__name__)


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


class TiktokenCounter:
    """Token counter backed by ``tiktoken``.

    Falls back through ``cl100k_base`` and finally a whitespace heuristic so
    that token counting never raises in production paths.
    """

    def __init__(self, model_name: str = "gpt-4o") -> None:
        self._encoder = self._load_encoder(model_name)

    @staticmethod
    def _load_encoder(model_name: str) -> tiktoken.Encoding | None:
        try:
            return tiktoken.encoding_for_model(model_name)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "tiktoken model '%s' unavailable (%s); using cl100k_base",
                model_name,
                exc,
            )
        try:
            return tiktoken.get_encoding("cl100k_base")
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("tiktoken unavailable: %s; using whitespace heuristic", exc)
            return None

    def count(self, text: str) -> int:
        if not text:
            return 0
        if self._encoder is None:
            return len(text.split())
        try:
            return len(self._encoder.encode(text))
        except Exception as exc:
            logger.warning("Token encoding failed (%s); using whitespace heuristic", exc)
            return len(text.split())
