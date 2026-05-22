"""HTML cleanup utilities.

Uses ``selectolax`` (≈2-3× faster than lxml/pyquery) when available with a
graceful fallback to pure regex for environments where selectolax is missing.
The cleaner removes scripts, styles, hidden nodes and elements relying on
``display:none`` / ``visibility:hidden`` / ``aria-hidden``.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

try:  # pragma: no cover - import-time only
    from selectolax.parser import HTMLParser  # type: ignore

    _HAS_SELECTOLAX = True
except Exception:  # pragma: no cover
    HTMLParser = None  # type: ignore[assignment]
    _HAS_SELECTOLAX = False


_REMOVE_SELECTORS: tuple[str, ...] = (
    "style",
    "script",
    "noscript",
    "[hidden]",
    '[style*="display:none"]',
    '[style*="display: none"]',
    '[style*="visibility:hidden"]',
    '[style*="visibility: hidden"]',
    '[aria-hidden="true"]',
)

_FALLBACK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"<style\b[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL),
    re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL),
    re.compile(r"<noscript\b[^>]*>.*?</noscript>", re.IGNORECASE | re.DOTALL),
)


def clean_html(html: str) -> str:
    """Return ``html`` with hidden / inert nodes removed.

    The function is best-effort: any parser failure logs at DEBUG and returns
    the original input unchanged so downstream conversion can still proceed.
    """
    if not html:
        return html

    if _HAS_SELECTOLAX:
        try:
            tree = HTMLParser(html)
            for selector in _REMOVE_SELECTORS:
                for node in tree.css(selector):
                    node.decompose()
            return tree.html or ""
        except Exception as exc:
            logger.debug("selectolax cleanup failed: %s", exc)

    cleaned = html
    for pattern in _FALLBACK_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    return cleaned


def clean_html_bytes(data: bytes, encoding: str = "utf-8") -> bytes:
    """Convenience wrapper for byte input/output (used to avoid extra decodes)."""
    text = data.decode(encoding, errors="ignore")
    return clean_html(text).encode(encoding, errors="ignore")
