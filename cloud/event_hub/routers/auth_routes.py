"""Auth routes."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from cloud.event_hub.auth import (
    AuthContext,
    TokenRequest,
    auth_mode,
    can_admin,
    data_scope_for_role,
    get_auth_context,
    login_user,
)

router = APIRouter()


@router.post("/auth/token")
def auth_token(req: TokenRequest) -> Dict[str, Any]:
    return login_user(req)


@router.get("/v1/auth/me")
def auth_me(auth: AuthContext = Depends(get_auth_context)) -> Dict[str, Any]:
    return {
        "username": auth.sub,
        "role": auth.role,
        "store_id": auth.store_id,
        "data_scope": data_scope_for_role(auth.role),
        "can_admin": can_admin(auth),
        "auth_mode": auth_mode(),
    }
