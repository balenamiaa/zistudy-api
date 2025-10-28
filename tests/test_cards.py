from __future__ import annotations

import json

import pytest
from httpx import AsyncClient

from zistudy_api.db.repositories.study_cards import StudyCardRepository
from zistudy_api.db.repositories.users import UserRepository
from zistudy_api.domain.enums import CardType
from zistudy_api.domain.schemas.study_cards import NoteCardData, StudyCardCreate

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


async def _promote_to_superuser(session_maker, email: str) -> str:
    async with session_maker() as session:
        repo = UserRepository(session)
        user = await repo.get_by_email(email)
        assert user is not None, "User must exist before promotion."
        user.is_superuser = True
        await session.commit()
        return user.id


async def test_card_import_and_search(client: AsyncClient) -> None:
    token = await _register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    import_payload = {
        "cards": [
            {
                "card_type": "mcq_single",
                "data": {
                    "generator": {"model": "secret-model"},
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
    card_ids = [int(card["id"]) for card in cards]

    search_resp = await client.post(
        "/api/v1/study-cards/search",
        json={"query": "powerhouse", "filters": {}},
        headers=headers,
    )
    assert search_resp.status_code == 200
    results = search_resp.json()
    assert results["total"] == 1
    assert results["items"][0]["card"]["card_type"] == "mcq_single"

    hidden_meta_search = await client.post(
        "/api/v1/study-cards/search",
        json={"query": "secret-model", "filters": {}},
        headers=headers,
    )
    assert hidden_meta_search.status_code == 200
    assert hidden_meta_search.json()["total"] == 0

    list_resp = await client.get("/api/v1/study-cards", headers=headers)
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

    other_token = await _register_and_login(client, "other@example.com")
    other_headers = {"Authorization": f"Bearer {other_token}"}

    other_search_resp = await client.post(
        "/api/v1/study-cards/search",
        json={"query": "powerhouse", "filters": {}},
        headers=other_headers,
    )
    assert other_search_resp.status_code == 200
    assert other_search_resp.json()["total"] == 0

    other_list_resp = await client.get("/api/v1/study-cards", headers=other_headers)
    assert other_list_resp.status_code == 200
    assert other_list_resp.json()["total"] == 0

    forbidden_delete = await client.delete(
        f"/api/v1/study-cards/{card_ids[0]}",
        headers=other_headers,
    )
    assert forbidden_delete.status_code == 403


async def test_list_study_cards_page_size_guard(client: AsyncClient) -> None:
    response = await client.get("/api/v1/study-cards", params={"page_size": 1000})
    assert response.status_code == 422


async def test_study_card_import_json_endpoint(client: AsyncClient) -> None:
    token = await _register_and_login(client, "json-owner@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    payload = [
        {
            "card_type": "note",
            "data": {"title": "JSON Note", "markdown": "Payload from JSON."},
            "difficulty": 2,
        }
    ]
    resp = await client.post(
        "/api/v1/study-cards/import/json",
        content=json.dumps(payload),
        headers={**headers, "content-type": "application/json"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert isinstance(data, list) and data[0]["card_type"] == "note"


async def test_non_owner_cannot_view_or_update_card(client: AsyncClient) -> None:
    owner_token = await _register_and_login(client, "card-owner@example.com")
    other_token = await _register_and_login(client, "card-guest@example.com")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    other_headers = {"Authorization": f"Bearer {other_token}"}

    create_resp = await client.post(
        "/api/v1/study-cards",
        json={
            "card_type": "mcq_single",
            "difficulty": 2,
            "data": {
                "prompt": "Owner question?",
                "options": [{"id": "A", "text": "Option"}],
                "correct_option_ids": ["A"],
                "glossary": {},
                "connections": [],
                "references": [],
                "numerical_ranges": [],
            },
        },
        headers=owner_headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    card_id = create_resp.json()["id"]

    forbidden_view = await client.get(f"/api/v1/study-cards/{card_id}", headers=other_headers)
    assert forbidden_view.status_code == 403

    forbidden_update = await client.put(
        f"/api/v1/study-cards/{card_id}",
        json={"difficulty": 5},
        headers=other_headers,
    )
    assert forbidden_update.status_code == 403


async def test_system_cards_visible_and_admin_manageable(
    client: AsyncClient, session_maker
) -> None:
    # Register admin and promote to superuser before login to embed claim in token.
    admin_email = "admin@example.com"
    admin_password = "SuperSecret1!"
    await client.post(
        "/api/v1/auth/register",
        json={"email": admin_email, "password": admin_password, "full_name": "Admin"},
    )
    await _promote_to_superuser(session_maker, admin_email)
    admin_login = await client.post(
        "/api/v1/auth/login",
        json={"email": admin_email, "password": admin_password},
    )
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

    guest_token = await _register_and_login(client, "guest@example.com")
    guest_headers = {"Authorization": f"Bearer {guest_token}"}

    async with session_maker() as session:
        repo = StudyCardRepository(session)
        card = await repo.create(
            StudyCardCreate(
                card_type=CardType.NOTE,
                difficulty=1,
                data=NoteCardData(generator=None, title="System Note", markdown="Visible to all."),
            ),
            owner_id=None,
        )
        await session.commit()
        card_id = card.id

    anonymous_list = await client.get("/api/v1/study-cards")
    assert anonymous_list.status_code == 200
    anon_payload = anonymous_list.json()
    assert any(item["id"] == card_id for item in anon_payload["items"])

    forbidden_delete = await client.delete(
        f"/api/v1/study-cards/{card_id}",
        headers=guest_headers,
    )
    assert forbidden_delete.status_code == 403

    admin_delete = await client.delete(
        f"/api/v1/study-cards/{card_id}",
        headers=admin_headers,
    )
    assert admin_delete.status_code == 204
