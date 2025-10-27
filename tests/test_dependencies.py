from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import cast

import pytest
from fastapi import HTTPException

from zistudy_api.api import dependencies as deps
from zistudy_api.config.settings import Settings
from zistudy_api.services.ai import AiStudyCardService

pytestmark = pytest.mark.asyncio


class _DummyGeminiClient:
    def __init__(self, **_: object) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


async def test_get_ai_study_card_service_yields_service(
    session_maker,
    settings: Settings,
    monkeypatch,
) -> None:
    monkeypatch.setattr(deps, "GeminiGenerativeClient", lambda **kwargs: _DummyGeminiClient())

    async with session_maker() as session:
        generator = cast(
            AsyncGenerator[AiStudyCardService, None],
            deps.get_ai_study_card_service(session, settings),
        )
        service = await anext(generator)
        assert isinstance(service, AiStudyCardService)
        await generator.aclose()


async def test_get_ai_study_card_service_requires_api_key(
    session_maker,
    settings: Settings,
) -> None:
    async with session_maker() as session:
        missing_key_settings = settings.model_copy(update={"gemini_api_key": None})
        generator = deps.get_ai_study_card_service(session, missing_key_settings)
        with pytest.raises(HTTPException):
            await anext(generator)
