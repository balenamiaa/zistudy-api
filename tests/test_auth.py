from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_register_login_refresh_logout(client: AsyncClient) -> None:
    # Register a new user
    register_resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "auth@example.com", "password": "Secure123!", "full_name": "Auth User"},
    )
    assert register_resp.status_code == 201

    # Login
    login_resp = await client.post(
        "/api/v1/auth/login", json={"email": "auth@example.com", "password": "Secure123!"}
    )
    assert login_resp.status_code == 200
    tokens = login_resp.json()
    assert "access_token" in tokens and "refresh_token" in tokens

    # Access protected route
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    me_resp = await client.get("/api/v1/auth/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "auth@example.com"

    # Refresh token
    refresh_resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refresh_resp.status_code == 200
    new_tokens = refresh_resp.json()
    assert "access_token" in new_tokens

    # Logout (invalidate refresh tokens)
    logout_resp = await client.post("/api/v1/auth/logout", headers=headers)
    assert logout_resp.status_code == 204

    # Refresh should now fail
    refresh_fail = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refresh_fail.status_code == 401


async def test_api_key_lifecycle(client: AsyncClient) -> None:
    password = "ApiKey123!"
    await client.post(
        "/api/v1/auth/register",
        json={"email": "apikey@example.com", "password": password, "full_name": "Key User"},
    )
    login_resp = await client.post(
        "/api/v1/auth/login", json={"email": "apikey@example.com", "password": password}
    )
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    create_resp = await client.post(
        "/api/v1/auth/api-keys",
        json={"name": "CI", "expires_in_hours": 24},
        headers=headers,
    )
    assert create_resp.status_code == 201
    key_payload = create_resp.json()
    assert key_payload["key"].startswith("")

    list_resp = await client.get("/api/v1/auth/api-keys", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    key_id = list_resp.json()[0]["id"]
    delete_resp = await client.delete(f"/api/v1/auth/api-keys/{key_id}", headers=headers)
    assert delete_resp.status_code == 204

    list_after = await client.get("/api/v1/auth/api-keys", headers=headers)
    assert list_after.status_code == 200
    assert list_after.json() == []
