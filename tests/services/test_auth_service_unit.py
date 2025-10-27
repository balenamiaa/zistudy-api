from __future__ import annotations

import pytest
from fastapi import HTTPException

from zistudy_api.config.settings import Settings
from zistudy_api.db.repositories.api_keys import ApiKeyRepository
from zistudy_api.db.repositories.refresh_tokens import RefreshTokenRepository
from zistudy_api.db.repositories.users import UserRepository
from zistudy_api.domain.schemas.auth import APIKeyCreate, RefreshRequest, UserCreate, UserLogin
from zistudy_api.services.auth import AuthService

pytestmark = pytest.mark.asyncio


async def _get_auth_service(session) -> AuthService:
    return AuthService(
        session=session,
        user_repository=UserRepository(session),
        refresh_tokens=RefreshTokenRepository(session),
        api_keys=ApiKeyRepository(session),
        settings=Settings(
            database_url="sqlite+aiosqlite:///./auth-test.db",
            jwt_secret="supersecretjwt123!",
        ),
    )


async def test_auth_service_register_and_login(session_maker) -> None:
    async with session_maker() as session:
        service = await _get_auth_service(session)

        user = await service.register_user(
            UserCreate(email="user@example.com", password="Secret123!", full_name="U Sing")
        )
        assert user.email == "user@example.com"

        tokens = await service.authenticate(UserLogin(email="user@example.com", password="Secret123!"))
        assert tokens.access_token
        assert tokens.refresh_token

        refreshed = await service.refresh(RefreshRequest(refresh_token=tokens.refresh_token))
        assert refreshed.refresh_token != tokens.refresh_token

        session_user = await service.parse_access_token(tokens.access_token)
        assert session_user.email == "user@example.com"


async def test_auth_service_api_key_flow(session_maker) -> None:
    async with session_maker() as session:
        service = await _get_auth_service(session)
        user = await service.register_user(
            UserCreate(email="keyer@example.com", password="Secret123!", full_name="Key User")
        )
        tokens = await service.authenticate(UserLogin(email=user.email, password="Secret123!"))
        assert tokens.access_token

        api_key = await service.create_api_key(user.id, APIKeyCreate(name="CI", expires_in_hours=1))
        masked = await service.list_api_keys(user.id)
        assert masked[0].key == "***masked***"

        session_user = await service.authenticate_api_key(api_key.key)
        assert session_user.id == user.id

        await service.delete_api_key(user.id, api_key.id)
        assert await service.list_api_keys(user.id) == []


async def test_auth_service_invalid_login(session_maker) -> None:
    async with session_maker() as session:
        service = await _get_auth_service(session)
        user_payload = UserCreate(email="fail@example.com", password="Secret123!", full_name=None)
        await service.register_user(user_payload)

        with pytest.raises(HTTPException) as exc:
            await service.authenticate(UserLogin(email=user_payload.email, password="wrong"))
        assert exc.value.status_code == 401
