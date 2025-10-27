from __future__ import annotations

from datetime import datetime

from pydantic import EmailStr, Field, SecretStr

from zistudy_api.domain.schemas.base import BaseSchema


class UserCreate(BaseSchema):
    email: EmailStr
    password: SecretStr = Field(..., min_length=8)
    full_name: str | None = Field(default=None, max_length=255)


class UserLogin(BaseSchema):
    email: EmailStr
    password: SecretStr


class UserRead(BaseSchema):
    id: str
    email: EmailStr
    full_name: str | None = None
    is_active: bool = True
    is_superuser: bool = False
    created_at: datetime
    updated_at: datetime


class TokenPair(BaseSchema):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Access token lifetime in seconds")


class RefreshRequest(BaseSchema):
    refresh_token: str


class TokenResponse(BaseSchema):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class SessionUser(BaseSchema):
    id: str
    email: EmailStr
    full_name: str | None = None
    is_superuser: bool = False
    scopes: list[str] = Field(default_factory=list)


class APIKeyCreate(BaseSchema):
    name: str | None = Field(default=None, max_length=255)
    expires_in_hours: int | None = Field(default=None, ge=1, le=24 * 365)


class APIKeyRead(BaseSchema):
    id: int
    key: str
    name: str | None = None
    created_at: datetime
    expires_at: datetime | None = None
    last_used_at: datetime | None = None


__all__ = [
    "APIKeyCreate",
    "APIKeyRead",
    "RefreshRequest",
    "SessionUser",
    "TokenPair",
    "TokenResponse",
    "UserCreate",
    "UserLogin",
    "UserRead",
]
