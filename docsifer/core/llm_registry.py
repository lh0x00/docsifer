"""TTL-cached registry of MarkItDown instances configured with an LLM client.

Creating an ``OpenAI`` client (and the wrapping ``MarkItDown``) is expensive
because each ``OpenAI`` instance owns a private ``httpx.Client`` connection
pool and triggers a TLS handshake on first use.  We cache one instance per
``(api_key_hash, base_url, model)`` tuple so repeated requests reuse the same
TCP/TLS session.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
from cachetools import TTLCache
from markitdown import MarkItDown
from openai import OpenAI

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LLMConfig:
    api_key: str
    base_url: str
    model: str

    @property
    def cache_key(self) -> str:
        digest = hashlib.sha256(self.api_key.encode("utf-8")).hexdigest()[:16]
        return f"{digest}|{self.base_url}|{self.model}"

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any] | None,
        *,
        default_base_url: str,
        default_model: str,
    ) -> "LLMConfig | None":
        if not data:
            return None
        api_key = (data.get("api_key") or "").strip()
        if not api_key:
            return None
        base_url = (data.get("base_url") or default_base_url).strip().rstrip("/")
        model = (data.get("model") or default_model).strip()
        return cls(api_key=api_key, base_url=base_url, model=model)


class LLMRegistry:
    """Thread-safe TTL cache of LLM-enabled :class:`MarkItDown` instances."""

    def __init__(
        self,
        *,
        max_size: int = 16,
        ttl: int = 600,
        request_timeout: float = 60.0,
        connect_timeout: float = 10.0,
        max_retries: int = 2,
    ) -> None:
        self._cache: TTLCache[str, MarkItDown] = TTLCache(maxsize=max_size, ttl=ttl)
        self._lock = threading.Lock()
        self._request_timeout = request_timeout
        self._connect_timeout = connect_timeout
        self._max_retries = max_retries

    def get(self, config: LLMConfig) -> MarkItDown:
        """Return a cached or freshly built :class:`MarkItDown` for ``config``."""
        key = config.cache_key
        with self._lock:
            instance = self._cache.get(key)
            if instance is not None:
                return instance
            instance = self._build(config)
            self._cache[key] = instance
            logger.info(
                "LLM client created",
                extra={"base_url": config.base_url, "model": config.model},
            )
            return instance

    def _build(self, config: LLMConfig) -> MarkItDown:
        client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=httpx.Timeout(
                self._request_timeout, connect=self._connect_timeout
            ),
            max_retries=self._max_retries,
        )
        return MarkItDown(llm_client=client, llm_model=config.model)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
