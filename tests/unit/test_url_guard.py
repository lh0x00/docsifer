import pytest

from docsifer.core.url_guard import validate_url
from docsifer.exceptions import InvalidInputError


def test_rejects_empty() -> None:
    with pytest.raises(InvalidInputError):
        validate_url("")


def test_rejects_disallowed_scheme() -> None:
    with pytest.raises(InvalidInputError):
        validate_url("file:///etc/passwd")


def test_rejects_loopback(monkeypatch) -> None:
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", ("127.0.0.1", 0))],
    )
    with pytest.raises(InvalidInputError):
        validate_url("http://localhost/")


def test_rejects_link_local_metadata(monkeypatch) -> None:
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", ("169.254.169.254", 0))],
    )
    with pytest.raises(InvalidInputError):
        validate_url("http://169.254.169.254/latest/meta-data")


def test_accepts_public(monkeypatch) -> None:
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", ("93.184.216.34", 0))],  # example.com
    )
    out = validate_url("https://example.com/foo")
    assert out.startswith("https://example.com")


def test_allow_private_when_configured(monkeypatch) -> None:
    out = validate_url(
        "http://localhost/x",
        allow_private_networks=True,
    )
    assert "localhost" in out
