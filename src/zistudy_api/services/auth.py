from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from zistudy_api.config.settings import Settings, get_settings
from zistudy_api.core.security import (
    create_access_token,
    generate_api_key,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from zistudy_api.db.repositories.api_keys import ApiKeyRepository
from zistudy_api.db.repositories.refresh_tokens import RefreshTokenRepository
from zistudy_api.db.repositories.users import UserRepository
from zistudy_api.domain.schemas.auth import (
    APIKeyCreate,
    APIKeyRead,
    RefreshRequest,
    SessionUser,
    TokenPair,
    UserCreate,
    UserLogin,
    UserRead,
)


class AuthService:
    """Coordinate authentication, authorization, and token flows."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        user_repository: UserRepository,
        refresh_tokens: RefreshTokenRepository,
        api_keys: ApiKeyRepository,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._users = user_repository
        self._refresh_tokens = refresh_tokens
        self._api_keys = api_keys
        self._settings = settings or get_settings()

    async def register_user(self, payload: UserCreate) -> UserRead:
        """Register a user account with hashed credentials."""
        existing = await self._users.get_by_email(payload.email)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already in use",
            )

        password_hash = hash_password(payload.password.get_secret_value())
        entity = await self._users.create(
            email=payload.email,
            password_hash=password_hash,
            full_name=payload.full_name,
        )
        await self._session.commit()
        return UserRead.model_validate(entity)

    async def authenticate(self, credentials: UserLogin) -> TokenPair:
        """Validate credentials and issue an access/refresh token pair."""
        user = await self._users.get_by_email(credentials.email)
        if user is None or not verify_password(
            credentials.password.get_secret_value(), user.password_hash
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User disabled")

        await self._users.touch_last_login(user.id)
        tokens = await self._issue_tokens(user_id=user.id, email=user.email, scopes=[])
        await self._session.commit()
        return tokens

    async def refresh(self, payload: RefreshRequest) -> TokenPair:
        """Rotate refresh tokens and return fresh access credentials."""
        token_str = payload.refresh_token
        token_hash = hash_token(token_str)
        record = await self._refresh_tokens.get_by_hash(token_hash)
        if record is None or record.revoked:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

        expires_at = record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(tz=timezone.utc):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")

        await self._refresh_tokens.revoke(record.id)
        tokens = await self._issue_tokens(user_id=record.user_id)
        await self._session.commit()
        return tokens

    async def revoke_refresh_tokens(self, user_id: str) -> None:
        """Revoke all refresh tokens belonging to the specified user."""
        await self._refresh_tokens.revoke_all_for_user(user_id)
        await self._session.commit()

    async def create_api_key(self, user_id: str, payload: APIKeyCreate) -> APIKeyRead:
        """Create and return a new API key, including the plaintext secret."""
        key = generate_api_key(self._settings)
        key_hash = hash_token(key)
        entity = await self._api_keys.create(
            user_id=user_id,
            key_hash=key_hash,
            name=payload.name,
            expires_in_hours=payload.expires_in_hours,
        )
        await self._session.commit()
        return APIKeyRead(
            id=entity.id,
            key=key,
            name=entity.name,
            created_at=entity.created_at,
            expires_at=entity.expires_at,
            last_used_at=entity.last_used_at,
        )

    async def list_api_keys(self, user_id: str) -> list[APIKeyRead]:
        """List API keys for a user with masked secrets."""
        records = await self._api_keys.list_for_user(user_id)
        return [
            APIKeyRead(
                id=record.id,
                key="***masked***",
                name=record.name,
                created_at=record.created_at,
                expires_at=record.expires_at,
                last_used_at=record.last_used_at,
            )
            for record in records
        ]

    async def delete_api_key(self, user_id: str, api_key_id: int) -> None:
        """Delete an API key owned by the specified user."""
        records = await self._api_keys.list_for_user(user_id)
        if not any(record.id == api_key_id for record in records):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
        await self._api_keys.delete(api_key_id)
        await self._session.commit()

    async def authenticate_api_key(self, api_key: str) -> SessionUser:
        """Resolve an API key into a session user, enforcing expiry rules."""
        key_hash = hash_token(api_key)
        record = await self._api_keys.get_by_hash(key_hash)
        if record is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
        if record.expires_at:
            expires_at = record.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= datetime.now(tz=timezone.utc):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="API key expired"
                )
        await self._api_keys.touch_last_used(record.id)
        await self._session.commit()
        user = await self._users.get_by_id(record.user_id)
        if user is None or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
        return SessionUser(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            is_superuser=user.is_superuser,
            scopes=["api:read", "api:write"],
        )

    async def parse_access_token(self, token: str) -> SessionUser:
        """Parse a JWT access token into a session user."""
        from zistudy_api.core.security import decode_token

        payload = decode_token(token, self._settings)
        user_id = payload.get("sub")
        if not isinstance(user_id, str):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

        user = await self._users.get_by_id(user_id)
        if user is None or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

        scopes = payload.get("scopes", [])
        if not isinstance(scopes, list):
            scopes = []

        return SessionUser(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            is_superuser=user.is_superuser,
            scopes=[str(scope) for scope in scopes],
        )

    async def _issue_tokens(
        self,
        *,
        user_id: str,
        email: str | None = None,
        scopes: list[str] | None = None,
    ) -> TokenPair:
        if email is None:
            user = await self._users.get_by_id(user_id)
            if user is None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")
            email = user.email
            scopes = scopes or []
        expires_delta = timedelta(minutes=self._settings.access_token_exp_minutes)
        access_token = create_access_token(
            subject=user_id,
            settings=self._settings,
            claims={"email": email, "scopes": scopes or []},
            expires_delta=expires_delta,
        )
        refresh_token = generate_refresh_token(self._settings)
        refresh_hash = hash_token(refresh_token)
        refresh_exp = datetime.now(tz=timezone.utc) + timedelta(
            minutes=self._settings.refresh_token_exp_minutes
        )
        await self._refresh_tokens.create(
            token_hash=refresh_hash,
            user_id=user_id,
            expires_at=refresh_exp,
        )
        await self._session.flush()
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=int(expires_delta.total_seconds()),
        )


__all__ = ["AuthService"]
