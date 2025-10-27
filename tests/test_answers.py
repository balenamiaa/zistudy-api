from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _auth_headers(client: AsyncClient, email: str) -> dict[str, str]:
    password = "Answer123!"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Answer User"},
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _create_card(client: AsyncClient, headers: dict[str, str]) -> int:
    resp = await client.post(
        "/api/v1/study-cards",
        json={
            "card_type": "mcq_single",
            "data": {"question": "1+1?", "options": [1, 2], "answer": 1},
            "difficulty": 1,
        },
        headers=headers,
    )
    data = resp.json()
    assert isinstance(data, dict)
    return int(data["id"])


async def _create_set_with_card(client: AsyncClient, headers: dict[str, str]) -> tuple[int, int]:
    card_id = await _create_card(client, headers)
    set_resp = await client.post(
        "/api/v1/study-sets",
        json={"title": "Math", "description": "Test", "is_private": False},
        headers=headers,
    )
    set_id = set_resp.json()["study_set"]["id"]
    await client.post(
        "/api/v1/study-sets/add-cards",
        json={"study_set_id": set_id, "card_ids": [card_id], "card_type": "mcq_single"},
        headers=headers,
    )
    return set_id, card_id


async def test_submit_and_history(client: AsyncClient) -> None:
    headers = await _auth_headers(client, "answerer@example.com")
    set_id, card_id = await _create_set_with_card(client, headers)

    submit_resp = await client.post(
        "/api/v1/answers",
        json={
            "study_card_id": card_id,
            "answer_type": "mcq",
            "data": {"selected": 1},
            "is_correct": True,
        },
        headers=headers,
    )
    assert submit_resp.status_code == 201

    history_resp = await client.get("/api/v1/answers/history", headers=headers)
    history_payload = history_resp.json()
    assert history_payload["total"] == 1
    assert history_payload["items"][0]["study_card_id"] == card_id

    stats_resp = await client.get(f"/api/v1/answers/cards/{card_id}/stats", headers=headers)
    stats = stats_resp.json()
    assert stats["attempts"] == 1
    assert stats["correct"] == 1

    progress_resp = await client.get(
        "/api/v1/answers/study-sets/progress",
        params=[("study_set_ids", set_id)],
        headers=headers,
    )
    progress = progress_resp.json()
    assert progress[0]["attempted_cards"] == 1
