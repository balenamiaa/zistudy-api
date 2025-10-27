from __future__ import annotations

import base64
from typing import Annotated, cast

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError

from zistudy_api.api.dependencies import JobServiceDependency, get_current_session_user
from zistudy_api.domain.schemas.ai import StudyCardGenerationRequest
from zistudy_api.domain.schemas.auth import SessionUser
from zistudy_api.domain.schemas.jobs import JobSummary
from zistudy_api.services.job_processors import process_ai_generation_job
from zistudy_api.services.jobs import ProcessorTask

router = APIRouter(prefix="/ai", tags=["AI"])

PDF_CONTENT_TYPES = {
    "application/pdf",
    "application/x-pdf",
    "application/acrobat",
    "applications/vnd.pdf",
    "text/pdf",
    "text/x-pdf",
}


@router.post(
    "/study-cards/generate",
    response_model=JobSummary,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_study_cards(
    payload: Annotated[str, Form(description="JSON encoded StudyCardGenerationRequest")],
    pdfs: Annotated[list[UploadFile], File(default_factory=list)],
    job_service: JobServiceDependency,
    _: Annotated[SessionUser, Depends(get_current_session_user)],
) -> JobSummary:
    """Queue an asynchronous job that generates study cards from the supplied PDFs."""
    try:
        request_model = StudyCardGenerationRequest.model_validate_json(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid generation payload.",
        ) from exc

    encoded_documents: list[dict[str, str | None]] = []
    for upload in pdfs:
        try:
            if upload.content_type and upload.content_type not in PDF_CONTENT_TYPES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unsupported content type: {upload.content_type}",
                )

            data = await upload.read()
            if data:
                encoded_documents.append(
                    {
                        "filename": upload.filename,
                        "content": base64.b64encode(data).decode("ascii"),
                    }
                )
        finally:
            await upload.close()

    job_payload = {
        "request": request_model.model_dump(mode="json"),
        "documents": encoded_documents,
    }

    summary = await job_service.enqueue(
        job_type="ai_generate_study_cards",
        owner_id=_.id,
        payload=job_payload,
        processor_task=cast(ProcessorTask, process_ai_generation_job),
    )
    return summary


__all__ = ["generate_study_cards", "router"]
