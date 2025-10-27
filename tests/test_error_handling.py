from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_404_error_envelope(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/study-sets/9999")
    assert resp.status_code == 404
    payload = resp.json()
    assert "error" in payload
    assert payload["error"]["code"] == 404
    assert "message" in payload["error"]


async def test_401_error_envelope(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/study-sets",
        json={"title": "Unauthorized", "description": "", "is_private": False},
    )
    assert resp.status_code == 401
    payload = resp.json()
    assert payload["error"]["code"] == 401
    assert payload["error"]["message"]
