from __future__ import annotations

import asyncio
import base64
from typing import Any

import pytest
from tests.utils import create_pdf_with_text_and_image

from zistudy_api.db.repositories.jobs import JobRepository
from zistudy_api.db.repositories.study_cards import StudyCardRepository
from zistudy_api.db.repositories.users import UserRepository
from zistudy_api.domain.enums import CardType
from zistudy_api.domain.schemas.ai import StudyCardGenerationRequest
from zistudy_api.domain.schemas.auth import SessionUser
from zistudy_api.domain.schemas.jobs import JobStatus
from zistudy_api.domain.schemas.study_cards import CardOption, McqSingleCardData, StudyCardCreate
from zistudy_api.domain.schemas.study_sets import AddCardsToSet, StudySetCreate
from zistudy_api.services import job_processors
from zistudy_api.services.study_sets import StudySetService

pytestmark = pytest.mark.asyncio


async def test_execute_async_runs_coroutine() -> None:
    flag: dict[str, bool] = {"ran": False}

    async def sample_task() -> None:
        flag["ran"] = True

    job_processors._execute_async(sample_task())

    assert flag["ran"] is True


async def test_execute_async_propagates_exceptions() -> None:
    async def failing() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        job_processors._execute_async(failing())


async def _seed_study_set(session, owner_id: str) -> tuple[int, int]:
    card_repo = StudyCardRepository(session)
    card = await card_repo.create(
        StudyCardCreate(
            card_type=CardType.MCQ_SINGLE,
            difficulty=2,
            data=McqSingleCardData(
                prompt="What is 2+2?",
                options=[
                    CardOption(id="A", text="3"),
                    CardOption(id="B", text="4"),
                ],
                correct_option_ids=["B"],
            ),
        ),
        owner_id=owner_id,
    )

    study_set_service = StudySetService(session)
    meta = await study_set_service.create_study_set(
        StudySetCreate(title="Arithmetic", description="Basic maths", is_private=False),
        user_id=owner_id,
    )
    requester = SessionUser(id=owner_id, email=f"{owner_id}@example.com", is_superuser=False)
    await study_set_service.add_cards(
        AddCardsToSet(
            study_set_id=meta.study_set.id,
            card_ids=[card.id],
            card_type=CardType.MCQ_SINGLE,
        ),
        requester=requester,
    )
    return meta.study_set.id, card.id


async def test_process_clone_job_creates_new_set(session_maker, monkeypatch) -> None:
    monkeypatch.setattr(job_processors, "SESSION_FACTORY", session_maker, raising=False)

    async with session_maker() as session:
        user = await UserRepository(session).create(
            email="clone-owner@example.com",
            password_hash="hash",
            full_name="Clone Owner",
        )
        study_set_id, _ = await _seed_study_set(session, user.id)
        job = await JobRepository(session).create(
            job_type="clone",
            owner_id=user.id,
            payload={
                "owner_id": user.id,
                "study_set_ids": [study_set_id],
                "title_prefix": "Copy - ",
            },
        )
        await session.commit()
        job_id = job.id

    await job_processors._process_clone_job(job_id)

    async with session_maker() as session:
        repo = JobRepository(session)
        stored = await repo.get(job_id)
        assert stored is not None
        assert stored.status == JobStatus.COMPLETED.value
        assert stored.result is not None
        created_ids = stored.result["created_set_ids"]
        assert len(created_ids) == 1
        clone_id = created_ids[0]

        service = StudySetService(session)
        clone_meta = await service.get_study_set(clone_id)
        assert clone_meta.study_set.title.startswith("Copy - ")
        assert clone_meta.card_count == 1


async def test_process_export_job_records_payload(session_maker, monkeypatch) -> None:
    monkeypatch.setattr(job_processors, "SESSION_FACTORY", session_maker, raising=False)

    async with session_maker() as session:
        user = await UserRepository(session).create(
            email="export-owner@example.com",
            password_hash="hash",
            full_name="Export Owner",
        )
        study_set_id, card_id = await _seed_study_set(session, user.id)
        job = await JobRepository(session).create(
            job_type="export",
            owner_id=user.id,
            payload={"owner_id": user.id, "study_set_ids": [study_set_id]},
        )
        await session.commit()
        job_id = job.id

    await job_processors._process_export_job(job_id)

    async with session_maker() as session:
        repo = JobRepository(session)
        stored = await repo.get(job_id)
        assert stored is not None
        assert stored.status == JobStatus.COMPLETED.value
        assert stored.result is not None
        result = stored.result["study_sets"]
        assert len(result) == 1
        exported = result[0]
        assert exported["study_set"]["study_set"]["id"] == study_set_id
        assert exported["cards"][0]["card"]["id"] == card_id
        assert exported["cards"][0]["card"]["card_type"] == CardType.MCQ_SINGLE.value


class _StubGeminiClient:
    closed = False

    def __init__(self, **_: Any) -> None:
        pass

    async def aclose(self) -> None:
        type(self).closed = True


class _StubResult:
    payload: dict[str, Any] = {
        "cards": [],
        "retention_aid": None,
        "summary": {"card_count": 0, "sources": [], "model_used": "stub", "temperature_applied": 0.0},
        "raw_generation": {},
    }

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return self.payload


class _StubAiService:
    instances: list["_StubAiService"] = []

    def __init__(self, *, session, agent, pdf_strategy, **_: Any) -> None:  # noqa: D401 - signature parity
        self.session = session
        self.agent = agent
        self.pdf_strategy = pdf_strategy
        self.calls: list[tuple[StudyCardGenerationRequest, list[Any]]] = []
        self.__class__.instances.append(self)

    async def generate_from_pdfs(
        self,
        request: StudyCardGenerationRequest,
        files,
    ) -> _StubResult:
        self.calls.append((request, list(files)))
        return _StubResult()


async def test_process_ai_generation_job_stores_result(session_maker, monkeypatch) -> None:
    monkeypatch.setattr(job_processors, "SESSION_FACTORY", session_maker, raising=False)
    monkeypatch.setattr(job_processors, "GeminiGenerativeClient", _StubGeminiClient)
    monkeypatch.setattr(job_processors, "AiStudyCardService", _StubAiService)

    pdf_bytes = create_pdf_with_text_and_image("AI generation payload")
    encoded = base64.b64encode(pdf_bytes).decode("ascii")

    async with session_maker() as session:
        user = await UserRepository(session).create(
            email="ai-owner@example.com",
            password_hash="hash",
            full_name="AI Owner",
        )
        job = await JobRepository(session).create(
            job_type="ai_generate_study_cards",
            owner_id=user.id,
            payload={
                "request": {"topics": ["Neurology"], "target_card_count": 1},
                "documents": [{"filename": "neurology.pdf", "content": encoded}],
            },
        )
        await session.commit()
        job_id = job.id

    await job_processors._process_ai_generation_job(job_id)

    async with session_maker() as session:
        repo = JobRepository(session)
        stored = await repo.get(job_id)
        assert stored is not None
        assert stored.status == JobStatus.COMPLETED.value
        assert stored.result == _StubResult.payload

    stub_instances = _StubAiService.instances
    assert stub_instances, "AI generation service should be initialised"


@pytest.mark.asyncio
async def test_clone_job_failure_is_sanitized(session_maker, monkeypatch) -> None:
    monkeypatch.setattr(job_processors, "SESSION_FACTORY", session_maker, raising=False)

    class FailingStudySetService:
        def __init__(self, session) -> None:
            self._session = session

        async def clone_study_sets(self, *args, **kwargs):
            raise RuntimeError("Sensitive backend detail")

    monkeypatch.setattr(job_processors, "StudySetService", FailingStudySetService)

    async with session_maker() as session:
        user = await UserRepository(session).create(
            email="clone-failure@example.com",
            password_hash="hash",
            full_name="Clone Failure",
        )
        job = await JobRepository(session).create(
            job_type="clone",
            owner_id=user.id,
            payload={
                "owner_id": user.id,
                "study_set_ids": [1],
                "title_prefix": None,
            },
        )
        await session.commit()
        job_id = job.id

    with pytest.raises(RuntimeError):
        await job_processors._process_clone_job(job_id)

    async with session_maker() as session:
        repo = JobRepository(session)
        stored = await repo.get(job_id)
        assert stored is not None
        assert stored.status == JobStatus.FAILED.value
        assert stored.error == job_processors.GENERIC_JOB_ERROR_MESSAGE
        assert "Sensitive" not in stored.error


@pytest.mark.asyncio
async def test_export_job_failure_is_sanitized(session_maker, monkeypatch) -> None:
    monkeypatch.setattr(job_processors, "SESSION_FACTORY", session_maker, raising=False)

    class FailingExportStudySetService:
        def __init__(self, session) -> None:
            self._session = session

        async def export_study_sets(self, *args, **kwargs):
            raise RuntimeError("Export failure detail")

    monkeypatch.setattr(job_processors, "StudySetService", FailingExportStudySetService)

    async with session_maker() as session:
        user = await UserRepository(session).create(
            email="export-failure@example.com",
            password_hash="hash",
            full_name="Export Failure",
        )
        job = await JobRepository(session).create(
            job_type="export",
            owner_id=user.id,
            payload={"owner_id": user.id, "study_set_ids": [1]},
        )
        await session.commit()
        job_id = job.id

    with pytest.raises(RuntimeError):
        await job_processors._process_export_job(job_id)

    async with session_maker() as session:
        repo = JobRepository(session)
        stored = await repo.get(job_id)
        assert stored is not None
        assert stored.status == JobStatus.FAILED.value
        assert stored.error == job_processors.GENERIC_JOB_ERROR_MESSAGE


@pytest.mark.asyncio
async def test_ai_generation_job_failure_is_sanitized(session_maker, monkeypatch) -> None:
    monkeypatch.setattr(job_processors, "SESSION_FACTORY", session_maker, raising=False)

    class StubClient:
        closed = False

        def __init__(self, **_: Any) -> None:
            pass

        async def aclose(self) -> None:
            type(self).closed = True

    class FailingAiService:
        def __init__(self, *, session, agent, pdf_strategy, **_: Any) -> None:
            self.session = session
            self.agent = agent
            self.pdf_strategy = pdf_strategy

        async def generate_from_pdfs(self, *args, **kwargs):
            raise RuntimeError("AI failure detail")

    monkeypatch.setattr(job_processors, "GeminiGenerativeClient", StubClient)
    monkeypatch.setattr(job_processors, "AiStudyCardService", FailingAiService)

    pdf_bytes = create_pdf_with_text_and_image("Failure")
    encoded = base64.b64encode(pdf_bytes).decode("ascii")

    async with session_maker() as session:
        user = await UserRepository(session).create(
            email="ai-failure@example.com",
            password_hash="hash",
            full_name="AI Failure",
        )
        job = await JobRepository(session).create(
            job_type="ai_generate_study_cards",
            owner_id=user.id,
            payload={
                "request": {"topics": ["Neurology"], "target_card_count": 1},
                "documents": [{"filename": "neurology.pdf", "content": encoded}],
            },
        )
        await session.commit()
        job_id = job.id

    with pytest.raises(RuntimeError):
        await job_processors._process_ai_generation_job(job_id)

    async with session_maker() as session:
        repo = JobRepository(session)
        stored = await repo.get(job_id)
        assert stored is not None
        assert stored.status == JobStatus.FAILED.value
        assert stored.error == job_processors.GENERIC_JOB_ERROR_MESSAGE
    assert StubClient.closed is True
