from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Select, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from zistudy_api.db.models import RefreshToken


class RefreshTokenRepository:
    """Persistence layer for refresh tokens."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        *,
        token_hash: str,
        user_id: str,
        expires_at: datetime,
    ) -> RefreshToken:
        entity = RefreshToken(
            token_hash=token_hash,
            user_id=user_id,
            expires_at=expires_at,
        )
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        stmt: Select[tuple[RefreshToken]] = select(RefreshToken).where(
            RefreshToken.token_hash == token_hash
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke(self, token_id: int) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.id == token_id)
            .values(revoked=True, revoked_at=datetime.now(tz=timezone.utc))
        )

    async def revoke_all_for_user(self, user_id: str) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id)
            .values(revoked=True, revoked_at=datetime.now(tz=timezone.utc))
        )

    async def delete_expired(self) -> None:
        await self._session.execute(
            delete(RefreshToken).where(RefreshToken.expires_at < datetime.now(tz=timezone.utc))
        )

    async def delete(self, token_id: int) -> None:
        await self._session.execute(delete(RefreshToken).where(RefreshToken.id == token_id))


__all__ = ["RefreshTokenRepository"]
