from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _register_and_login(client: AsyncClient, email: str = "user@example.com") -> str:
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
    data = login.json()
    assert isinstance(data, dict)
    token = data.get("access_token")
    assert isinstance(token, str)
    return token


async def test_card_import_and_search(client: AsyncClient) -> None:
    token = await _register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    import_payload = {
        "cards": [
            {
                "card_type": "mcq_single",
                "data": {
                    "prompt": "What is the powerhouse of the cell?",
                    "options": [
                        {"id": "A", "text": "Nucleus"},
                        {"id": "B", "text": "Mitochondria"},
                        {"id": "C", "text": "Ribosome"},
                    ],
                    "correct_option_ids": ["B"],
                    "glossary": {},
                    "connections": [],
                    "references": [],
                    "numerical_ranges": [],
                },
                "difficulty": 2,
            },
            {
                "card_type": "note",
                "data": {
                    "title": "Photosynthesis",
                    "markdown": "Photosynthesis occurs in chloroplasts.",
                },
                "difficulty": 1,
            },
        ]
    }

    import_resp = await client.post(
        "/api/v1/study-cards/import", json=import_payload, headers=headers
    )
    assert import_resp.status_code == 201, import_resp.text
    cards = import_resp.json()
    assert len(cards) == 2

    search_resp = await client.post(
        "/api/v1/study-cards/search",
        json={"query": "powerhouse", "filters": {}},
        headers=headers,
    )
    assert search_resp.status_code == 200
    results = search_resp.json()
    assert results["total"] == 1
    assert results["items"][0]["card"]["card_type"] == "mcq_single"

    list_resp = await client.get("/api/v1/study-cards")
    assert list_resp.status_code == 200
    listed = list_resp.json()
    assert listed["total"] == 2

    create_set_resp = await client.post(
        "/api/v1/study-sets",
        json={"title": "Biology", "description": "Intro", "is_private": False},
        headers=headers,
    )
    assert create_set_resp.status_code == 201
    study_set = create_set_resp.json()["study_set"]

    not_in_set_resp = await client.get(
        f"/api/v1/study-cards/not-in-set/{study_set['id']}", headers=headers
    )
    assert not_in_set_resp.status_code == 200
    not_in_set = not_in_set_resp.json()
    assert not_in_set["total"] == 2
