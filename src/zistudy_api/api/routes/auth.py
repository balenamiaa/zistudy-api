from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from zistudy_api.api.dependencies import (
    get_auth_service,
    get_current_session_user,
)
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
from zistudy_api.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["Auth"])


AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
CurrentUserDependency = Annotated[SessionUser, Depends(get_current_session_user)]


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: UserCreate,
    auth_service: AuthServiceDependency,
) -> UserRead:
    """Create a new user account and return the persisted profile."""
    return await auth_service.register_user(payload)


@router.post("/login", response_model=TokenPair)
async def login_user(
    payload: UserLogin,
    auth_service: AuthServiceDependency,
) -> TokenPair:
    """Exchange credentials for a short-lived access token pair."""
    return await auth_service.authenticate(payload)


@router.post("/refresh", response_model=TokenPair)
async def refresh_token(
    payload: RefreshRequest,
    auth_service: AuthServiceDependency,
) -> TokenPair:
    """Rotate refresh credentials and issue a fresh access/refresh token pair."""
    return await auth_service.refresh(payload)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout_user(
    user: CurrentUserDependency,
    auth_service: AuthServiceDependency,
) -> None:
    """Revoke all refresh tokens associated with the current user."""
    await auth_service.revoke_refresh_tokens(user.id)


@router.get("/me", response_model=SessionUser)
async def get_me(user: CurrentUserDependency) -> SessionUser:
    """Return the authenticated session user."""
    return user


@router.get("/api-keys", response_model=list[APIKeyRead])
async def list_api_keys(
    user: CurrentUserDependency,
    auth_service: AuthServiceDependency,
) -> list[APIKeyRead]:
    """List API keys that belong to the current user."""
    return await auth_service.list_api_keys(user.id)


@router.post("/api-keys", response_model=APIKeyRead, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: APIKeyCreate,
    user: CurrentUserDependency,
    auth_service: AuthServiceDependency,
) -> APIKeyRead:
    """Create a new API key for the current user."""
    return await auth_service.create_api_key(user.id, payload)


@router.delete("/api-keys/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    api_key_id: int,
    user: CurrentUserDependency,
    auth_service: AuthServiceDependency,
) -> None:
    """Delete an API key owned by the current user."""
    await auth_service.delete_api_key(user.id, api_key_id)


__all__ = ["router"]
