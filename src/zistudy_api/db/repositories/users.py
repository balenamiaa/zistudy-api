from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from zistudy_api.db.models import UserAccount


class UserRepository:
    """Persistence layer for user accounts."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        *,
        email: str,
        password_hash: str,
        full_name: str | None,
        is_superuser: bool = False,
    ) -> UserAccount:
        entity = UserAccount(
            email=email,
            password_hash=password_hash,
            full_name=full_name,
            is_superuser=is_superuser,
        )
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def get_by_email(self, email: str) -> UserAccount | None:
        stmt: Select[tuple[UserAccount]] = select(UserAccount).where(UserAccount.email == email)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: str) -> UserAccount | None:
        stmt: Select[tuple[UserAccount]] = select(UserAccount).where(UserAccount.id == user_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def touch_last_login(self, user_id: str) -> None:
        await self._session.execute(
            update(UserAccount)
            .where(UserAccount.id == user_id)
            .values(updated_at=datetime.now(tz=timezone.utc))
        )


__all__ = ["UserRepository"]
