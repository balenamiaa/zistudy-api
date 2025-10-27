from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_tag_suggestions_and_popular(client: AsyncClient) -> None:
    # Seed a user and create tags via study sets
    password = "Secret123!"
    await client.post(
        "/api/v1/auth/register",
        json={"email": "tagger@example.com", "password": password, "full_name": "Tagger"},
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "tagger@example.com", "password": password},
    )
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create two study sets with overlapping tags
    for title, tags in [("Neuro", ["brain", "science"]), ("Cardio", ["heart", "science"])]:
        resp = await client.post(
            "/api/v1/study-sets",
            json={"title": title, "description": title, "is_private": False, "tag_names": tags},
            headers=headers,
        )
        assert resp.status_code == 201

    # Search for tags containing 'sc'
    search_resp = await client.get("/api/v1/tags/search", params={"query": "sc", "limit": 10})
    assert search_resp.status_code == 200
    search_payload = search_resp.json()
    assert search_payload["total"] >= 1
    names = {item["name"] for item in search_payload["items"]}
    assert "science" in names

    # Fetch popular tags
    popular_resp = await client.get("/api/v1/tags/popular", params={"limit": 5})
    assert popular_resp.status_code == 200
    popular = popular_resp.json()
    assert any(entry["tag"]["name"] == "science" for entry in popular)
    assert popular[0]["usage_count"] >= 1
