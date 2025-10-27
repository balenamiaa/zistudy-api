from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from zistudy_api.db.models import ApiKey


class ApiKeyRepository:
    """Persistence operations for API keys."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        *,
        user_id: str,
        key_hash: str,
        name: str | None,
        expires_in_hours: int | None,
    ) -> ApiKey:
        expires_at = (
            datetime.now(tz=timezone.utc) + timedelta(hours=expires_in_hours)
            if expires_in_hours is not None
            else None
        )
        entity = ApiKey(
            user_id=user_id,
            key_hash=key_hash,
            name=name,
            expires_at=expires_at,
        )
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def list_for_user(self, user_id: str) -> list[ApiKey]:
        stmt: Select[tuple[ApiKey]] = select(ApiKey).where(ApiKey.user_id == user_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_hash(self, key_hash: str) -> ApiKey | None:
        stmt: Select[tuple[ApiKey]] = select(ApiKey).where(ApiKey.key_hash == key_hash)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete(self, api_key_id: int) -> None:
        await self._session.execute(delete(ApiKey).where(ApiKey.id == api_key_id))

    async def touch_last_used(self, api_key_id: int) -> None:
        await self._session.execute(
            update(ApiKey)
            .where(ApiKey.id == api_key_id)
            .values(last_used_at=datetime.now(tz=timezone.utc))
        )


__all__ = ["ApiKeyRepository"]
