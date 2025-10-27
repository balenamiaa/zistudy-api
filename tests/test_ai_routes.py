from __future__ import annotations

import pytest

from tests.utils import create_pdf_with_text_and_image
from zistudy_api.domain.schemas.ai import StudyCardGenerationRequest
from zistudy_api.domain.schemas.jobs import JobStatus

pytestmark = pytest.mark.asyncio


async def _authorize(client) -> str:
    password = "Secret123!"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "aiuser@example.com", "password": password, "full_name": "AI Tester"},
    )
    assert resp.status_code == 201
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "aiuser@example.com", "password": password},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    assert isinstance(token, str)
    return token


async def test_generate_study_cards_endpoint(app, client, monkeypatch) -> None:
    calls: list[tuple[StudyCardGenerationRequest, list[str]]] = []

    async def stub_generate_from_pdfs(self, request, files):
        calls.append(
            (
                request,
                [getattr(file, "filename", None) for file in files],
            )
        )
        return type(
            "StubResult",
            (),
            {
                "model_dump": lambda _self, mode="json": {
                    "cards": [],
                    "retention_aid": None,
                    "summary": {
                        "card_count": 0,
                        "sources": [getattr(file, "filename", None) for file in files],
                        "model_used": "models/gemini-2.5-pro",
                        "temperature_applied": 0.1,
                    },
                    "raw_generation": {},
                }
            },
        )()

    monkeypatch.setattr(
        "zistudy_api.services.job_processors.AiStudyCardService",
        lambda *args, **kwargs: type(
            "StubAiServiceWrapper",
            (),
            {"generate_from_pdfs": stub_generate_from_pdfs},
        )(),
    )

    token = await _authorize(client)
    headers = {"Authorization": f"Bearer {token}"}

    payload = StudyCardGenerationRequest(topics=["Toxicology"]).model_dump_json()
    pdf_bytes = create_pdf_with_text_and_image("Beta-blocker overdose case")

    response = await client.post(
        "/api/v1/ai/study-cards/generate",
        files=[
            ("payload", (None, payload)),
            ("pdfs", ("case.pdf", pdf_bytes, "application/pdf")),
        ],
        headers=headers,
    )

    assert response.status_code == 202, response.text
    data = response.json()
    job_id = data["id"]
    assert JobStatus(data["status"]) == JobStatus.PENDING

    job_response = await client.get(f"/api/v1/jobs/{job_id}", headers=headers)
    assert job_response.status_code == 200
    job_payload = job_response.json()
    assert JobStatus(job_payload["status"]) == JobStatus.COMPLETED
    assert job_payload["result"]["summary"]["sources"] == ["case.pdf"]
    assert calls, "AI service should be invoked"
    request_record, filenames = calls[0]
    assert request_record.topics == ["Toxicology"]
    assert filenames == ["case.pdf"]


async def test_generate_study_cards_rejects_invalid_payload(app, client) -> None:
    token = await _authorize(client)
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.post(
        "/api/v1/ai/study-cards/generate",
        files=[
            ("payload", (None, "not-json")),
        ],
        headers=headers,
    )

    assert response.status_code == 400


async def test_generate_study_cards_rejects_invalid_pdf_type(app, client) -> None:
    token = await _authorize(client)
    headers = {"Authorization": f"Bearer {token}"}

    payload = StudyCardGenerationRequest(topics=["Toxicology"]).model_dump_json()

    response = await client.post(
        "/api/v1/ai/study-cards/generate",
        files=[
            ("payload", (None, payload)),
            ("pdfs", ("notes.txt", b"hello world", "text/plain")),
        ],
        headers=headers,
    )

    assert response.status_code == 400


async def test_generate_study_cards_requires_authentication(client) -> None:
    pdf_bytes = create_pdf_with_text_and_image("Auth required")
    payload = StudyCardGenerationRequest(topics=["Security"]).model_dump_json()

    response = await client.post(
        "/api/v1/ai/study-cards/generate",
        files=[
            ("payload", (None, payload)),
            ("pdfs", ("case.pdf", pdf_bytes, "application/pdf")),
        ],
    )

    assert response.status_code == 401
