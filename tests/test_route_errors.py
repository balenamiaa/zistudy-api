from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _register_and_login(client: AsyncClient, email: str) -> str:
    password = "Secret123!"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Tester"},
    )
    assert resp.status_code == 201, resp.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    assert isinstance(token, str)
    return token


async def test_answer_routes_404(client: AsyncClient) -> None:
    token = await _register_and_login(client, "answer-404@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "study_card_id": 9999,
        "answer_type": "mcq_single",
        "data": {"answer": 0},
    }
    submit = await client.post("/api/v1/answers", json=payload, headers=headers)
    assert submit.status_code == 404

    resp = await client.get("/api/v1/answers/9999", headers=headers)
    assert resp.status_code == 404


async def test_study_card_routes_error_paths(client: AsyncClient) -> None:
    token = await _register_and_login(client, "cards-errors@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get("/api/v1/study-cards/99999")
    assert resp.status_code == 404

    resp = await client.put(
        "/api/v1/study-cards/99999",
        json={"data": {"question": "?", "answer": 1}},
        headers=headers,
    )
    assert resp.status_code == 404

    resp = await client.delete("/api/v1/study-cards/99999", headers=headers)
    assert resp.status_code == 404

    bad_json = await client.post(
        "/api/v1/study-cards/import/json",
        content="not-json",
        headers={**headers, "content-type": "application/json"},
    )
    assert bad_json.status_code == 400


async def test_jobs_route_returns_404_for_unknown_job(client: AsyncClient) -> None:
    token = await _register_and_login(client, "jobs@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.get("/api/v1/jobs/99999", headers=headers)
    assert response.status_code == 404


async def test_tags_routes(client: AsyncClient) -> None:
    create = await client.post(
        "/api/v1/tags",
        json=[{"name": " physiology "}, {"name": "pharmacology"}],
    )
    assert create.status_code == 201
    created = create.json()
    assert {tag["name"] for tag in created} == {"physiology", "pharmacology"}

    list_resp = await client.get("/api/v1/tags")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) >= 2

    filtered = await client.get("/api/v1/tags", params={"names": ["physiology"]})
    assert filtered.status_code == 200
    assert filtered.json()[0]["name"] == "physiology"

    search = await client.get("/api/v1/tags/search", params={"query": "phys", "limit": 5})
    assert search.status_code == 200
    data = search.json()
    assert data["total"] >= 1
    assert any(item["name"] == "physiology" for item in data["items"])

    popular = await client.get("/api/v1/tags/popular", params={"limit": 5})
    assert popular.status_code == 200
