from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime, timezone
from threading import Thread

from sqlalchemy.ext.asyncio import async_sessionmaker

from zistudy_api.celery_app import celery_app
from zistudy_api.config.settings import get_settings
from zistudy_api.db.repositories.jobs import JobRepository
from zistudy_api.db.session import get_sessionmaker
from zistudy_api.domain.schemas.ai import StudyCardGenerationRequest
from zistudy_api.domain.schemas.jobs import JobStatus
from zistudy_api.services.ai import (
    AgentConfiguration,
    AiStudyCardService,
    DocumentIngestionService,
    GeminiGenerativeClient,
    IngestedPDFContextStrategy,
    NativePDFContextStrategy,
    PDFContextStrategy,
    StudyCardGenerationAgent,
    UploadedPDF,
)
from zistudy_api.services.study_sets import StudySetService

SESSION_FACTORY: async_sessionmaker | None = None

logger = logging.getLogger(__name__)

GENERIC_JOB_ERROR_MESSAGE = "Job failed; please contact support."


def _factory() -> async_sessionmaker:
    global SESSION_FACTORY
    if SESSION_FACTORY is None:
        SESSION_FACTORY = get_sessionmaker()
    return SESSION_FACTORY


def _execute_async(coro) -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)
    else:
        result: dict[str, Exception | None] = {"error": None}

        def runner() -> None:
            try:
                asyncio.run(coro)
            except Exception as exc:  # pragma: no cover - propagated below
                result["error"] = exc

        thread = Thread(target=runner, daemon=True)
        thread.start()
        thread.join()
        if result["error"] is not None:
            raise result["error"]


@celery_app.task(name="jobs.process_clone_job")
def process_clone_job(job_id: int) -> None:
    _execute_async(_process_clone_job(job_id))


async def _process_clone_job(job_id: int) -> None:
    session_factory = _factory()
    async with session_factory() as session:
        job_repo = JobRepository(session)
        job = await job_repo.get(job_id)
        if job is None:
            return

        logger.info("AI generation job fetched", extra={"job_id": job_id, "owner_id": job.owner_id})
        payload = job.payload
        owner_id: str = payload["owner_id"]
        study_set_ids: list[int] = payload["study_set_ids"]
        title_prefix: str | None = payload.get("title_prefix")

        await job_repo.set_status(
            job_id,
            status=JobStatus.IN_PROGRESS.value,
            started_at=datetime.now(tz=timezone.utc),
        )
        await session.commit()

        study_set_service = StudySetService(session)
        try:
            new_ids = await study_set_service.clone_study_sets(
                study_set_ids=study_set_ids,
                owner_id=owner_id,
                title_prefix=title_prefix,
            )
            await job_repo.set_result(job_id, {"created_set_ids": new_ids})
            await job_repo.set_status(
                job_id,
                status=JobStatus.COMPLETED.value,
                completed_at=datetime.now(tz=timezone.utc),
            )
            await session.commit()
        except Exception as exc:  # pragma: no cover
            await _mark_job_failed(
                job_repo=job_repo,
                job_id=job_id,
                session=session,
                log_message="Clone study set job failed",
                exc=exc,
            )
            raise


@celery_app.task(name="jobs.process_export_job")
def process_export_job(job_id: int) -> None:
    _execute_async(_process_export_job(job_id))


async def _process_export_job(job_id: int) -> None:
    session_factory = _factory()
    async with session_factory() as session:
        job_repo = JobRepository(session)
        job = await job_repo.get(job_id)
        if job is None:
            return
        payload = job.payload
        owner_id: str = payload["owner_id"]
        study_set_ids: list[int] = payload["study_set_ids"]

        await job_repo.set_status(
            job_id,
            status=JobStatus.IN_PROGRESS.value,
            started_at=datetime.now(tz=timezone.utc),
        )
        await session.commit()

        study_set_service = StudySetService(session)
        try:
            export_payload = await study_set_service.export_study_sets(
                study_set_ids=study_set_ids,
                user_id=owner_id,
            )
            await job_repo.set_result(job_id, {"study_sets": export_payload})
            await job_repo.set_status(
                job_id,
                status=JobStatus.COMPLETED.value,
                completed_at=datetime.now(tz=timezone.utc),
            )
            await session.commit()
        except Exception as exc:  # pragma: no cover
            await _mark_job_failed(
                job_repo=job_repo,
                job_id=job_id,
                session=session,
                log_message="Export study set job failed",
                exc=exc,
            )
            raise


@celery_app.task(name="jobs.process_ai_generation_job")
def process_ai_generation_job(job_id: int) -> None:
    _execute_async(_process_ai_generation_job(job_id))


async def _process_ai_generation_job(job_id: int) -> None:
    session_factory = _factory()
    async with session_factory() as session:
        job_repo = JobRepository(session)
        job = await job_repo.get(job_id)
        if job is None:
            return

        settings = get_settings()
        if not settings.gemini_api_key:
            await job_repo.set_status(
                job_id,
                status=JobStatus.FAILED.value,
                completed_at=datetime.now(tz=timezone.utc),
                error="Gemini API is not configured.",
            )
            await session.commit()
            return

        await job_repo.set_status(
            job_id,
            status=JobStatus.IN_PROGRESS.value,
            started_at=datetime.now(tz=timezone.utc),
        )
        await session.commit()

        payload = job.payload or {}
        request_payload = payload.get("request", {})
        document_payload = payload.get("documents", [])

        ingestion_service = DocumentIngestionService()
        client = GeminiGenerativeClient(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            endpoint=settings.gemini_endpoint,
            timeout=settings.gemini_request_timeout_seconds,
        )
        agent_config = AgentConfiguration(
            default_model=settings.gemini_model,
            default_temperature=settings.ai_generation_default_temperature,
            default_card_count=settings.ai_generation_default_card_count,
            max_card_count=settings.ai_generation_max_card_count,
            max_attempts=settings.ai_generation_max_attempts,
        )
        agent = StudyCardGenerationAgent(client=client, config=agent_config)
        pdf_strategy: PDFContextStrategy
        if settings.gemini_pdf_mode == "native":
            pdf_strategy = NativePDFContextStrategy(ingestor=ingestion_service)
        else:
            pdf_strategy = IngestedPDFContextStrategy(ingestor=ingestion_service)
        ai_service = AiStudyCardService(
            session=session,
            agent=agent,
            pdf_strategy=pdf_strategy,
        )

        try:
            request_model = StudyCardGenerationRequest.model_validate(request_payload)
            documents = [
                UploadedPDF(
                    filename=item.get("filename"),
                    payload=base64.b64decode(item["content"]),
                )
                for item in document_payload
                if isinstance(item, dict) and item.get("content")
            ]
            result = await ai_service.generate_from_pdfs(request_model, documents)
            await job_repo.set_result(job_id, result.model_dump(mode="json"))
            await job_repo.set_status(
                job_id,
                status=JobStatus.COMPLETED.value,
                completed_at=datetime.now(tz=timezone.utc),
            )
            await session.commit()
            card_count = getattr(getattr(result, "summary", None), "card_count", None)
            logger.info(
                "AI generation job completed",
                extra={"job_id": job_id, "card_count": card_count},
            )
        except Exception as exc:  # pragma: no cover
            await _mark_job_failed(
                job_repo=job_repo,
                job_id=job_id,
                session=session,
                log_message="AI generation job failed",
                exc=exc,
            )
            raise
        finally:
            await client.aclose()


__all__ = ["process_clone_job", "process_export_job", "process_ai_generation_job"]


async def _mark_job_failed(
    *,
    job_repo: JobRepository,
    job_id: int,
    session,
    log_message: str,
    exc: Exception,
) -> None:
    logger.exception(log_message, extra={"job_id": job_id})
    await job_repo.set_status(
        job_id,
        status=JobStatus.FAILED.value,
        completed_at=datetime.now(tz=timezone.utc),
        error=GENERIC_JOB_ERROR_MESSAGE,
    )
    await session.commit()
