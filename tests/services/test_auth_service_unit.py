from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException, status
from pydantic import SecretStr

from zistudy_api.config.settings import Settings
from zistudy_api.core.security import hash_token
from zistudy_api.db.repositories.api_keys import ApiKeyRepository
from zistudy_api.db.repositories.refresh_tokens import RefreshTokenRepository
from zistudy_api.db.repositories.users import UserRepository
from zistudy_api.domain.schemas.auth import (
    APIKeyCreate,
    RefreshRequest,
    UserCreate,
    UserLogin,
)
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
            UserCreate(
                email="user@example.com", password=SecretStr("Secret123!"), full_name="U Sing"
            )
        )
        assert user.email == "user@example.com"

        tokens = await service.authenticate(
            UserLogin(email="user@example.com", password=SecretStr("Secret123!"))
        )
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
            UserCreate(
                email="keyer@example.com", password=SecretStr("Secret123!"), full_name="Key User"
            )
        )
        tokens = await service.authenticate(
            UserLogin(email=user.email, password=SecretStr("Secret123!"))
        )
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
        user_payload = UserCreate(
            email="fail@example.com", password=SecretStr("Secret123!"), full_name=None
        )
        await service.register_user(user_payload)

        with pytest.raises(HTTPException) as exc:
            await service.authenticate(
                UserLogin(email=user_payload.email, password=SecretStr("wrong"))
            )
        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_register_duplicate_email(session_maker) -> None:
    async with session_maker() as session:
        service = await _get_auth_service(session)
        payload = UserCreate(
            email="duplicate@example.com", password=SecretStr("Secret123!"), full_name=None
        )
        await service.register_user(payload)
        with pytest.raises(HTTPException) as exc:
            await service.register_user(payload)
        assert exc.value.status_code == status.HTTP_409_CONFLICT


@pytest.mark.asyncio
async def test_authenticate_disabled_user(session_maker) -> None:
    async with session_maker() as session:
        service = await _get_auth_service(session)
        payload = UserCreate(
            email="disabled@example.com", password=SecretStr("Secret123!"), full_name=None
        )
        user = await service.register_user(payload)
        repo = UserRepository(session)
        entity = await repo.get_by_email(user.email)
        assert entity is not None
        entity.is_active = False
        await session.commit()

        with pytest.raises(HTTPException) as exc:
            await service.authenticate(
                UserLogin(email=user.email, password=SecretStr("Secret123!"))
            )
        assert exc.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_refresh_with_expired_token(session_maker) -> None:
    async with session_maker() as session:
        service = await _get_auth_service(session)
        payload = UserCreate(
            email="refresh@example.com", password=SecretStr("Secret123!"), full_name=None
        )
        user = await service.register_user(payload)
        tokens = await service.authenticate(
            UserLogin(email=user.email, password=SecretStr("Secret123!"))
        )

        repo = RefreshTokenRepository(session)
        record = await repo.get_by_hash(hash_token(tokens.refresh_token))
        assert record is not None
        record.expires_at = datetime.now(tz=timezone.utc) - timedelta(seconds=1)
        await session.commit()

        with pytest.raises(HTTPException) as exc:
            await service.refresh(RefreshRequest(refresh_token=tokens.refresh_token))
        assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_refresh_token_cannot_be_reused(session_maker) -> None:
    async with session_maker() as session:
        service = await _get_auth_service(session)
        payload = UserCreate(
            email="rotate@example.com", password=SecretStr("Secret123!"), full_name=None
        )
        user = await service.register_user(payload)
        tokens = await service.authenticate(
            UserLogin(email=user.email, password=SecretStr("Secret123!"))
        )

        new_tokens = await service.refresh(RefreshRequest(refresh_token=tokens.refresh_token))
        assert new_tokens.refresh_token != tokens.refresh_token

        with pytest.raises(HTTPException) as exc:
            await service.refresh(RefreshRequest(refresh_token=tokens.refresh_token))
        assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_authenticate_api_key_invalid(session_maker) -> None:
    async with session_maker() as session:
        service = await _get_auth_service(session)
        with pytest.raises(HTTPException) as exc:
            await service.authenticate_api_key("invalid-key")
        assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_parse_access_token_invalid_user(session_maker) -> None:
    async with session_maker() as session:
        service = await _get_auth_service(session)
        payload = UserCreate(
            email="delete@example.com", password=SecretStr("Secret123!"), full_name=None
        )
        user = await service.register_user(payload)
        tokens = await service.authenticate(
            UserLogin(email=user.email, password=SecretStr("Secret123!"))
        )

        repo = UserRepository(session)
        entity = await repo.get_by_email(user.email)
        assert entity is not None
        await session.delete(entity)
        await session.commit()

        with pytest.raises(HTTPException) as exc:
            await service.parse_access_token(tokens.access_token)
        assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
