"""MIME detection helpers.

Trust the file extension when present and recognized; fall back to libmagic
sniffing of just the first 4 KB to avoid reading entire large files into RAM.
"""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

logger = logging.getLogger(__name__)

# Lazy-import the optional ``magic`` dependency so the application keeps
# working when libmagic is unavailable.
try:  # pragma: no cover - environment dependent
    import magic as _magic  # type: ignore

    _HAS_MAGIC = True
except Exception as exc:  # pragma: no cover
    logger.warning("python-magic unavailable, falling back to extensions only: %s", exc)
    _magic = None  # type: ignore[assignment]
    _HAS_MAGIC = False

_SNIFF_BYTES = 4096


def detect_mime(path: Path, *, sniff_bytes: int = _SNIFF_BYTES) -> str | None:
    """Return the MIME type of ``path`` or ``None`` when unknown.

    Reads at most ``sniff_bytes`` from the start of the file.
    """
    if _HAS_MAGIC:
        try:
            with path.open("rb") as fh:
                head = fh.read(sniff_bytes)
            return _magic.from_buffer(head, mime=True) or None  # type: ignore[union-attr]
        except Exception as exc:
            logger.debug("magic sniff failed for %s: %s", path, exc)
    # Fallback: derive from extension
    guess, _ = mimetypes.guess_type(str(path))
    return guess


def guess_extension(mime: str | None) -> str | None:
    """Return a canonical ``.ext`` string for ``mime`` (or ``None``)."""
    if not mime:
        return None
    return mimetypes.guess_extension(mime)


def normalize_extension(
    path: Path,
    *,
    known_extensions: set[str] | None = None,
) -> Path:
    """Ensure ``path`` has a sensible extension.

    If the current extension is in ``known_extensions``, it is trusted.
    Otherwise we sniff the MIME type and rename the file in place using
    :func:`os.rename` (atomic, zero-copy).
    """
    suffix = path.suffix.lower()
    if known_extensions and suffix in known_extensions:
        return path

    mime = detect_mime(path)
    ext = guess_extension(mime)
    if not ext or ext.lower() == suffix:
        return path

    new_path = path.with_suffix(ext)
    try:
        path.rename(new_path)
        return new_path
    except OSError as exc:
        logger.warning("Could not rename %s -> %s: %s", path, new_path, exc)
        return path
