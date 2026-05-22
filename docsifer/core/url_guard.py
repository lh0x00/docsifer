"""SSRF protection for user-supplied URLs.

Validates scheme, blocks loopback / link-local / private / multicast /
reserved networks unless explicitly allowed via configuration.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

from ..exceptions import InvalidInputError

logger = logging.getLogger(__name__)


def _is_blocked_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_private
        or ip.is_unspecified
    )


def validate_url(
    url: str,
    *,
    allowed_schemes: list[str] | None = None,
    allow_private_networks: bool = False,
) -> str:
    """Return a sanitized URL string or raise :class:`InvalidInputError`.

    When ``allow_private_networks`` is ``False`` (default) we resolve the
    hostname and reject any address pointing at private/loopback ranges, which
    blocks the typical SSRF vectors (e.g. AWS metadata at 169.254.169.254).
    """
    if not url or not url.strip():
        raise InvalidInputError("URL must not be empty")

    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "").lower()
    schemes = [s.lower() for s in (allowed_schemes or ["http", "https"])]
    if scheme not in schemes:
        raise InvalidInputError(
            f"URL scheme '{scheme or '<none>'}' is not allowed",
            details={"allowed_schemes": schemes},
        )
    if not parsed.hostname:
        raise InvalidInputError("URL must include a hostname")

    if allow_private_networks:
        return parsed.geturl()

    host = parsed.hostname
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise InvalidInputError(
            f"Could not resolve host: {host}", details={"error": str(exc)}
        ) from exc

    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _is_blocked_address(ip):
            logger.warning("Blocked SSRF target host=%s ip=%s", host, ip_str)
            raise InvalidInputError(
                "URL points to a non-public address",
                details={"host": host},
            )

    return parsed.geturl()
