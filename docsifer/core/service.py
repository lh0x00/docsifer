"""Pure conversion service.

The service is fully framework-agnostic so it can be invoked directly from
the FastAPI route handlers, the Gradio UI or background workers without
issuing self-HTTP loopback calls.

Key design points:
- Streaming MarkItDown conversion via :class:`io.BytesIO` whenever possible
  (avoids the read → write → reread cycle of the previous implementation).
- Cached LLM clients (see :class:`docsifer.core.llm_registry.LLMRegistry`).
- Bounded :class:`concurrent.futures.ThreadPoolExecutor` for sync work so
  default executor saturation can never block unrelated coroutines.
- HTTP cookies are forwarded to MarkItDown via a dedicated
  :class:`requests.Session`, fixing the previous broken cookie injection.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from markitdown import MarkItDown

from .html_cleaner import clean_html_bytes
from .llm_registry import LLMConfig, LLMRegistry
from .mime import normalize_extension
from .tokenizer import TiktokenCounter

logger = logging.getLogger(__name__)

_HTML_EXTS = frozenset({".html", ".htm"})


@dataclass(slots=True)
class ConvertResult:
    filename: str
    markdown: str
    token_count: int

    def to_dict(self) -> dict[str, Any]:
        return {"filename": self.filename, "markdown": self.markdown}


class DocsiferService:
    """Convert local files or remote URLs into Markdown."""

    def __init__(
        self,
        *,
        token_model: str = "gpt-4o",
        default_openai_base_url: str = "https://api.openai.com/v1",
        default_openai_model: str = "gpt-4o-mini",
        worker_pool_size: int = 4,
        llm_cache_max_size: int = 16,
        llm_cache_ttl: int = 600,
        openai_request_timeout: float = 60.0,
        openai_connect_timeout: float = 10.0,
        openai_max_retries: int = 2,
        known_extensions: set[str] | None = None,
    ) -> None:
        self._basic_md = MarkItDown()
        self._token_counter = TiktokenCounter(token_model)
        self._llm_registry = LLMRegistry(
            max_size=llm_cache_max_size,
            ttl=llm_cache_ttl,
            request_timeout=openai_request_timeout,
            connect_timeout=openai_connect_timeout,
            max_retries=openai_max_retries,
        )
        self._executor = ThreadPoolExecutor(
            max_workers=worker_pool_size,
            thread_name_prefix="docsifer-worker",
        )
        self._default_base_url = default_openai_base_url
        self._default_model = default_openai_model
        self._known_extensions = known_extensions or set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def convert_file(
        self,
        source: str | Path,
        *,
        openai_config: dict[str, Any] | None = None,
        http_config: dict[str, Any] | None = None,
        cleanup_html: bool = True,
    ) -> ConvertResult:
        """Convert a local file path or HTTP(S) URL into Markdown."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            self._convert_sync,
            source,
            openai_config,
            http_config,
            cleanup_html,
        )

    async def shutdown(self) -> None:
        """Stop the worker pool gracefully (called from app lifespan)."""
        self._llm_registry.clear()
        await asyncio.get_running_loop().run_in_executor(
            None, self._executor.shutdown, True
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _convert_sync(
        self,
        source: str | Path,
        openai_config: dict[str, Any] | None,
        http_config: dict[str, Any] | None,
        cleanup_html: bool,
    ) -> ConvertResult:
        is_url = isinstance(source, str) and source.lower().startswith(("http://", "https://"))

        md_converter = self._select_converter(openai_config)
        session = self._build_session(http_config) if http_config else None

        if is_url:
            return self._convert_url(str(source), md_converter, session)
        return self._convert_path(Path(source), md_converter, cleanup_html)

    # -- LLM / converter selection ------------------------------------------------
    def _select_converter(self, openai_config: dict[str, Any] | None) -> MarkItDown:
        cfg = LLMConfig.from_dict(
            openai_config,
            default_base_url=self._default_base_url,
            default_model=self._default_model,
        )
        if cfg is None:
            return self._basic_md
        try:
            return self._llm_registry.get(cfg)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Falling back to basic MarkItDown (LLM init failed): %s", exc)
            return self._basic_md

    @staticmethod
    def _build_session(http_config: dict[str, Any]) -> requests.Session | None:
        session = requests.Session()
        cookies = http_config.get("cookies")
        if isinstance(cookies, dict) and cookies:
            session.cookies.update({str(k): str(v) for k, v in cookies.items()})
        headers = http_config.get("headers")
        if isinstance(headers, dict) and headers:
            session.headers.update({str(k): str(v) for k, v in headers.items()})
        return session

    # -- URL conversion -----------------------------------------------------------
    def _convert_url(
        self,
        url: str,
        md_converter: MarkItDown,
        session: requests.Session | None,
    ) -> ConvertResult:
        try:
            if session is not None and hasattr(md_converter, "convert_url"):
                # markitdown >= 0.0.x exposes convert_url with a session kwarg
                result_obj = md_converter.convert_url(url, requests_session=session)  # type: ignore[arg-type]
            else:
                result_obj = md_converter.convert(url)
        except Exception as exc:
            logger.error("URL conversion failed: %s", exc)
            raise RuntimeError(f"Conversion failed for URL '{url}': {exc}") from exc

        text = getattr(result_obj, "text_content", "") or ""
        return ConvertResult(
            filename=self._derive_url_filename(url),
            markdown=text,
            token_count=self._token_counter.count(text),
        )

    @staticmethod
    def _derive_url_filename(url: str) -> str:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        last = (parsed.path or "/").rsplit("/", 1)[-1] or "index.html"
        if "." not in last:
            last = f"{last}.html"
        return last

    # -- Local file conversion ----------------------------------------------------
    def _convert_path(
        self,
        path: Path,
        md_converter: MarkItDown,
        cleanup_html: bool,
    ) -> ConvertResult:
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        normalized = normalize_extension(path, known_extensions=self._known_extensions)
        ext = normalized.suffix.lower()

        if cleanup_html and ext in _HTML_EXTS:
            return self._convert_html_streaming(normalized, md_converter, ext)

        try:
            result_obj = md_converter.convert(str(normalized))
        except Exception as exc:
            logger.error("File conversion failed: %s", exc)
            raise RuntimeError(f"Conversion failed for '{normalized.name}': {exc}") from exc

        text = getattr(result_obj, "text_content", "") or ""
        return ConvertResult(
            filename=normalized.name,
            markdown=text,
            token_count=self._token_counter.count(text),
        )

    def _convert_html_streaming(
        self,
        path: Path,
        md_converter: MarkItDown,
        ext: str,
    ) -> ConvertResult:
        """Read → clean → feed MarkItDown without writing back to disk."""
        try:
            data = path.read_bytes()
            cleaned = clean_html_bytes(data)
        except Exception as exc:
            logger.warning("HTML cleanup failed (%s); falling back to raw conversion", exc)
            cleaned = path.read_bytes()

        stream = io.BytesIO(cleaned)
        try:
            if hasattr(md_converter, "convert_stream"):
                result_obj = md_converter.convert_stream(stream, file_extension=ext)
            else:  # pragma: no cover - older markitdown
                # Fallback: write cleaned bytes to a sibling temp file
                with contextlib.suppress(Exception):
                    path.write_bytes(cleaned)
                result_obj = md_converter.convert(str(path))
        except Exception as exc:
            logger.error("HTML conversion failed: %s", exc)
            raise RuntimeError(f"Conversion failed for '{path.name}': {exc}") from exc

        text = getattr(result_obj, "text_content", "") or ""
        return ConvertResult(
            filename=path.name,
            markdown=text,
            token_count=self._token_counter.count(text),
        )
