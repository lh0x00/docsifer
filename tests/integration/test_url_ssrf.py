import socket

import pytest


@pytest.mark.asyncio
async def test_url_pointing_to_localhost_is_blocked(client, monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", ("127.0.0.1", 0))],
    )
    resp = await client.post(
        "/v1/convert",
        data={"url": "http://localhost/secret"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "InvalidInputError"


@pytest.mark.asyncio
async def test_url_invalid_scheme(client) -> None:
    resp = await client.post(
        "/v1/convert",
        data={"url": "ftp://example.com/foo"},
    )
    assert resp.status_code == 400
