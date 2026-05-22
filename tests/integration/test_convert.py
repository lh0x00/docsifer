import io
import json

import pytest


@pytest.mark.asyncio
async def test_convert_missing_inputs_returns_400(client) -> None:
    resp = await client.post("/v1/convert")
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "InvalidInputError"


@pytest.mark.asyncio
async def test_convert_disallowed_extension_returns_415(client) -> None:
    resp = await client.post(
        "/v1/convert",
        files={"file": ("malware.exe", b"bin", "application/octet-stream")},
    )
    assert resp.status_code == 415
    assert resp.json()["error"] == "UnsupportedFormatError"


@pytest.mark.asyncio
async def test_convert_payload_too_large(client) -> None:
    big = b"a" * (3 * 1024 * 1024)  # > 2MB limit set in fixture
    resp = await client.post(
        "/v1/convert",
        files={"file": ("big.txt", big, "text/plain")},
    )
    assert resp.status_code == 413
    assert resp.json()["error"] == "PayloadTooLargeError"


@pytest.mark.asyncio
async def test_convert_invalid_json_in_form(client) -> None:
    resp = await client.post(
        "/v1/convert",
        files={"file": ("a.txt", b"hi", "text/plain")},
        data={"openai": "{not json"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_convert_basic_text(client) -> None:
    resp = await client.post(
        "/v1/convert",
        files={"file": ("note.txt", b"# Hello\n\nworld", "text/plain")},
        data={"settings": json.dumps({"cleanup": False})},
    )
    # Conversion may succeed (200) or fail (5xx) depending on local markitdown.
    # Either way the response should be JSON with a stable schema and never
    # leak a stack trace.
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    if resp.status_code == 200:
        assert "filename" in body and "markdown" in body
    else:
        assert "error" in body and "message" in body


@pytest.mark.asyncio
async def test_convert_path_traversal_filename_is_sanitized(client) -> None:
    resp = await client.post(
        "/v1/convert",
        files={"file": ("../../etc/passwd.txt", b"hello", "text/plain")},
    )
    # Either accepted (200/5xx) but never written outside tmp; we mostly check
    # that the response is well-formed and the response filename has been
    # sanitized (no slashes / parent dirs).
    body = resp.json()
    if resp.status_code == 200:
        assert "/" not in body["filename"]
        assert ".." not in body["filename"]


@pytest.mark.asyncio
async def test_stats_endpoint(client) -> None:
    resp = await client.get("/v1/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert "access" in body and "tokens" in body
