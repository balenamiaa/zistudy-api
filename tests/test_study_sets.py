from __future__ import annotations

import asyncio
from typing import Any, Dict

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
    data = login.json()
    assert isinstance(data, dict)
    token = data.get("access_token")
    assert isinstance(token, str)
    return token


async def test_bulk_add_and_delete_study_sets(client: AsyncClient) -> None:
    token = await _register_and_login(client, "owner@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Seed study cards
    import_resp = await client.post(
        "/api/v1/study-cards/import",
        json={
            "cards": [
                {
                    "card_type": "mcq_single",
                    "data": {"question": "2+2?", "options": [3, 4], "answer": 1},
                    "difficulty": 1,
                },
                {
                    "card_type": "mcq_single",
                    "data": {"question": "3+5?", "options": [7, 8], "answer": 1},
                    "difficulty": 1,
                },
            ]
        },
        headers=headers,
    )
    assert import_resp.status_code == 201
    cards = import_resp.json()
    card_ids = [card["id"] for card in cards]

    # Create study sets
    set_ids = []
    for title in ["Set A", "Set B"]:
        resp = await client.post(
            "/api/v1/study-sets",
            json={"title": title, "description": title, "is_private": False},
            headers=headers,
        )
        assert resp.status_code == 201
        set_ids.append(resp.json()["study_set"]["id"])

    bulk_add_resp = await client.post(
        "/api/v1/study-sets/bulk-add",
        json={"study_set_ids": set_ids, "card_ids": card_ids, "card_type": "mcq_single"},
        headers=headers,
    )
    assert bulk_add_resp.status_code == 200, bulk_add_resp.text
    bulk_summary = bulk_add_resp.json()
    assert bulk_summary["success_count"] == len(set_ids)

    # Confirm cards appear in the set listing
    cards_in_set_resp = await client.get(f"/api/v1/study-sets/{set_ids[0]}/cards", headers=headers)
    assert cards_in_set_resp.status_code == 200
    cards_in_set = cards_in_set_resp.json()
    assert cards_in_set["total"] == len(card_ids)

    bulk_delete_resp = await client.post(
        "/api/v1/study-sets/bulk-delete",
        json={"study_set_ids": set_ids},
        headers=headers,
    )
    assert bulk_delete_resp.status_code == 200
    delete_summary = bulk_delete_resp.json()
    assert delete_summary["success_count"] == len(set_ids)

    for set_id in set_ids:
        fetch_resp = await client.get(f"/api/v1/study-sets/{set_id}", headers=headers)
        assert fetch_resp.status_code == 404


async def test_create_and_delete_single_study_set(client: AsyncClient) -> None:
    token = await _register_and_login(client, "single-delete@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    create_resp = await client.post(
        "/api/v1/study-sets",
        json={"title": "To remove", "description": "Temp", "is_private": True},
        headers=headers,
    )
    assert create_resp.status_code == 201
    body = create_resp.json()
    study_set_id = body["study_set"]["id"]
    assert study_set_id > 0

    delete_resp = await client.delete(f"/api/v1/study-sets/{study_set_id}", headers=headers)
    assert delete_resp.status_code == 204

    check_resp = await client.get(f"/api/v1/study-sets/{study_set_id}", headers=headers)
    assert check_resp.status_code == 404


async def _await_job_completion(client: AsyncClient, token: str, job_id: int) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(50):
        resp = await client.get(f"/api/v1/jobs/{job_id}", headers=headers)
        assert resp.status_code == 200
        payload = resp.json()
        assert isinstance(payload, dict)
        if payload["status"] == "completed":
            return payload
        if payload["status"] == "failed":
            pytest.fail(f"Job failed: {payload['error']}")
        await asyncio.sleep(0.05)
    pytest.fail("Job did not complete in time")


async def test_clone_and_export_jobs(client: AsyncClient) -> None:
    token = await _register_and_login(client, "clone@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Seed one study set with tags and cards
    import_resp = await client.post(
        "/api/v1/study-cards/import",
        json={
            "cards": [
                {
                    "card_type": "mcq_single",
                    "data": {
                        "question": "Capital of France?",
                        "options": ["Paris", "Berlin"],
                        "answer": 0,
                    },
                    "difficulty": 1,
                }
            ]
        },
        headers=headers,
    )
    card_id = import_resp.json()[0]["id"]

    create_set_resp = await client.post(
        "/api/v1/study-sets",
        json={
            "title": "Geography",
            "description": "Europe",
            "is_private": False,
            "tag_names": ["geography", "europe"],
        },
        headers=headers,
    )
    study_set_id = create_set_resp.json()["study_set"]["id"]

    await client.post(
        "/api/v1/study-sets/add-cards",
        json={"study_set_id": study_set_id, "card_ids": [card_id], "card_type": "mcq_single"},
        headers=headers,
    )

    # Clone study set
    clone_resp = await client.post(
        "/api/v1/study-sets/clone",
        json={"study_set_ids": [study_set_id], "title_prefix": "Copy - "},
        headers=headers,
    )
    assert clone_resp.status_code == 202
    clone_job = clone_resp.json()
    clone_result = await _await_job_completion(client, token, clone_job["id"])
    created_ids = clone_result["result"]["created_set_ids"]
    assert len(created_ids) == 1
    cloned_set_id = created_ids[0]

    cloned_set_resp = await client.get(f"/api/v1/study-sets/{cloned_set_id}", headers=headers)
    assert cloned_set_resp.status_code == 200
    cloned_body = cloned_set_resp.json()
    assert cloned_body["study_set"]["title"].startswith("Copy - ")
    assert cloned_body["card_count"] == 1

    # Export study sets
    export_resp = await client.post(
        "/api/v1/study-sets/export",
        json={"study_set_ids": [study_set_id] + created_ids},
        headers=headers,
    )
    assert export_resp.status_code == 202
    export_job = export_resp.json()
    export_result = await _await_job_completion(client, token, export_job["id"])
    exported_sets = export_result["result"]["study_sets"]
    assert len(exported_sets) == 2
    ids = {item["study_set"]["study_set"]["id"] for item in exported_sets}
    assert ids == {study_set_id, cloned_set_id}
    assert exported_sets[0]["cards"], "Export should include card payloads"


async def test_study_set_permissions_and_can_access(client: AsyncClient) -> None:
    owner_token = await _register_and_login(client, "owner-perms@example.com")
    other_token = await _register_and_login(client, "guest-perms@example.com")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    other_headers = {"Authorization": f"Bearer {other_token}"}

    create_resp = await client.post(
        "/api/v1/study-sets",
        json={"title": "Private Set", "description": "Locked", "is_private": True},
        headers=owner_headers,
    )
    study_set_id = create_resp.json()["study_set"]["id"]

    update_attempt = await client.put(
        f"/api/v1/study-sets/{study_set_id}",
        json={"title": "Hacked"},
        headers=other_headers,
    )
    assert update_attempt.status_code == 403

    can_access = await client.get(f"/api/v1/study-sets/{study_set_id}/can-access", headers=other_headers)
    assert can_access.status_code == 200
    flags = can_access.json()
    assert flags == {"can_access": False, "can_modify": False}

    anonymous_check = await client.get(f"/api/v1/study-sets/{study_set_id}/can-access")
    assert anonymous_check.status_code == 200
    anon_flags = anonymous_check.json()
    assert anon_flags == {"can_access": False, "can_modify": False}

    listing_owner = await client.get(
        "/api/v1/study-sets",
        headers=owner_headers,
        params={"show_only_owned": True, "search": "Private"},
    )
    assert listing_owner.status_code == 200
    assert listing_owner.json()["total"] == 1

    listing_other = await client.get(
        "/api/v1/study-sets",
        headers=other_headers,
        params={"show_only_owned": True},
    )
    assert listing_other.status_code == 200
    assert listing_other.json()["total"] == 0


async def test_study_set_add_remove_cards_validation(client: AsyncClient) -> None:
    owner_token = await _register_and_login(client, "owner-cards@example.com")
    other_token = await _register_and_login(client, "guest-cards@example.com")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    other_headers = {"Authorization": f"Bearer {other_token}"}

    card_resp = await client.post(
        "/api/v1/study-cards",
        json={
            "card_type": "mcq_single",
            "data": {
                "prompt": "Hematology?",
                "options": [{"id": "A", "text": "RBC"}],
                "correct_option_ids": ["A"],
            },
            "difficulty": 2,
        },
        headers=owner_headers,
    )
    assert card_resp.status_code == 201, card_resp.text
    card_id = card_resp.json()["id"]

    set_resp = await client.post(
        "/api/v1/study-sets",
        json={"title": "Permissions", "description": "Checks", "is_private": True},
        headers=owner_headers,
    )
    study_set_id = set_resp.json()["study_set"]["id"]

    unauthorized_add = await client.post(
        "/api/v1/study-sets/add-cards",
        json={"study_set_id": study_set_id, "card_ids": [card_id], "card_type": "mcq_single"},
        headers=other_headers,
    )
    assert unauthorized_add.status_code == 403

    bad_card_add = await client.post(
        "/api/v1/study-sets/add-cards",
        json={"study_set_id": study_set_id, "card_ids": [999999], "card_type": "mcq_single"},
        headers=owner_headers,
    )
    assert bad_card_add.status_code == 400

    good_add = await client.post(
        "/api/v1/study-sets/add-cards",
        json={"study_set_id": study_set_id, "card_ids": [card_id], "card_type": "mcq_single"},
        headers=owner_headers,
    )
    assert good_add.status_code == 204

    unauthorized_remove = await client.post(
        "/api/v1/study-sets/remove-cards",
        json={"study_set_id": study_set_id, "card_ids": [card_id], "card_type": "mcq_single"},
        headers=other_headers,
    )
    assert unauthorized_remove.status_code == 403

    remove_resp = await client.post(
        "/api/v1/study-sets/remove-cards",
        json={"study_set_id": study_set_id, "card_ids": [card_id], "card_type": "mcq_single"},
        headers=owner_headers,
    )
    assert remove_resp.status_code == 204

    for_card_owner = await client.get(f"/api/v1/study-sets/for-card/{card_id}", headers=owner_headers)
    assert for_card_owner.status_code == 200
    assert isinstance(for_card_owner.json(), list)

    for_card_other = await client.get(f"/api/v1/study-sets/for-card/{card_id}", headers=other_headers)
    assert for_card_other.status_code == 200
    assert for_card_other.json() == []
