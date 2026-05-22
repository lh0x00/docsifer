import pytest


@pytest.mark.asyncio
async def test_healthz(client) -> None:
    resp = await client.get("/v1/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "X-Request-ID" in resp.headers


@pytest.mark.asyncio
async def test_readyz_when_analytics_disabled(client) -> None:
    resp = await client.get("/v1/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_security_headers(client) -> None:
    resp = await client.get("/v1/healthz")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    # Embedding policy is enforced via CSP ``frame-ancestors`` (allows the HF
    # Spaces hub to iframe the app), not the legacy ``X-Frame-Options`` header.
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "frame-ancestors" in csp
    assert "huggingface.co" in csp
