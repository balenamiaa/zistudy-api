from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_urlsafe
from typing import Any, Mapping, cast

import jwt
from passlib.context import CryptContext

from zistudy_api.config.settings import Settings

_password_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    """Return an argon2 hash for the supplied plaintext password."""

    return cast(str, _password_context.hash(password))


def verify_password(password: str, password_hash: str) -> bool:
    """Validate a plaintext password against the stored hash."""

    return bool(_password_context.verify(password, password_hash))


def create_access_token(
    *,
    subject: str,
    settings: Settings,
    claims: Mapping[str, Any] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT access token."""

    now = datetime.now(tz=timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
    }
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.access_token_exp_minutes)
    payload["exp"] = int((now + expires_delta).timestamp())
    if claims:
        payload.update(claims)

    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, settings: Settings) -> dict[str, Any]:
    """Decode and validate a JWT, returning the payload."""

    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    return cast(dict[str, Any], payload)


def generate_refresh_token(settings: Settings) -> str:
    """Return a random refresh token string."""

    return token_urlsafe(settings.refresh_token_length)


def generate_api_key(settings: Settings) -> str:
    """Return a random API key string."""

    return token_urlsafe(settings.api_key_length)


def hash_token(token: str) -> str:
    """Return a deterministic SHA-256 hash for storing opaque tokens."""

    return sha256(token.encode("utf-8")).hexdigest()


__all__ = [
    "create_access_token",
    "decode_token",
    "generate_api_key",
    "generate_refresh_token",
    "hash_token",
    "hash_password",
    "verify_password",
]
