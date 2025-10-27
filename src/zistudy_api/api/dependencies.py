from __future__ import annotations

from typing import Annotated, AsyncIterator

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from zistudy_api.config.settings import Settings, get_settings
from zistudy_api.db.repositories.api_keys import ApiKeyRepository
from zistudy_api.db.repositories.refresh_tokens import RefreshTokenRepository
from zistudy_api.db.repositories.users import UserRepository
from zistudy_api.db.session import get_session
from zistudy_api.domain.schemas.auth import SessionUser
from zistudy_api.services.ai import (
    AgentConfiguration,
    AiStudyCardService,
    DocumentIngestionService,
    GeminiGenerativeClient,
    IngestedPDFContextStrategy,
    NativePDFContextStrategy,
    PDFContextStrategy,
    StudyCardGenerationAgent,
)
from zistudy_api.services.auth import AuthService
from zistudy_api.services.jobs import JobService
from zistudy_api.services.study_cards import StudyCardService
from zistudy_api.services.study_sets import StudySetService
from zistudy_api.services.tags import TagService

AsyncSessionDependency = Annotated[AsyncSession, Depends(get_session)]

bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="JWTBearer",
    description="Paste a JWT access token obtained from `/api/v1/auth/login`.",
)
api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)

TokenDependency = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]
APIKeyDependency = Annotated[str | None, Depends(api_key_header)]


def get_study_set_service(session: AsyncSessionDependency) -> StudySetService:
    return StudySetService(session)


def get_study_card_service(session: AsyncSessionDependency) -> StudyCardService:
    return StudyCardService(session)


def get_tag_service(session: AsyncSessionDependency) -> TagService:
    return TagService(session)


def get_job_service(session: AsyncSessionDependency) -> JobService:
    return JobService(session)


def get_auth_service(session: AsyncSessionDependency) -> AuthService:
    user_repo = UserRepository(session)
    refresh_repo = RefreshTokenRepository(session)
    api_key_repo = ApiKeyRepository(session)
    return AuthService(
        session=session,
        user_repository=user_repo,
        refresh_tokens=refresh_repo,
        api_keys=api_key_repo,
    )


AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
JobServiceDependency = Annotated[JobService, Depends(get_job_service)]


async def get_ai_study_card_service(
    session: AsyncSessionDependency,
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[AiStudyCardService]:
    if not settings.gemini_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gemini API is not configured.",
        )

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
    service = AiStudyCardService(
        session=session,
        agent=agent,
        pdf_strategy=pdf_strategy,
    )
    try:
        yield service
    finally:
        await client.aclose()


AiStudyCardServiceDependency = Annotated[AiStudyCardService, Depends(get_ai_study_card_service)]


async def get_current_session_user(
    token: TokenDependency,
    api_key: APIKeyDependency,
    auth_service: AuthServiceDependency,
) -> SessionUser:
    if token and token.credentials:
        return await auth_service.parse_access_token(token.credentials)
    if api_key:
        return await auth_service.authenticate_api_key(api_key)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


async def get_optional_session_user(
    token: TokenDependency,
    api_key: APIKeyDependency,
    auth_service: AuthServiceDependency,
) -> SessionUser | None:
    if token and token.credentials:
        return await auth_service.parse_access_token(token.credentials)
    if api_key:
        return await auth_service.authenticate_api_key(api_key)
    return None


__all__ = [
    "AiStudyCardServiceDependency",
    "APIKeyDependency",
    "AsyncSessionDependency",
    "AuthServiceDependency",
    "JobServiceDependency",
    "TokenDependency",
    "get_ai_study_card_service",
    "get_auth_service",
    "get_current_session_user",
    "get_optional_session_user",
    "get_job_service",
    "get_study_card_service",
    "get_study_set_service",
    "get_tag_service",
]
