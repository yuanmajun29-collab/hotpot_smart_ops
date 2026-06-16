"""JWT + API Key authentication (DEV-102)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, APIKeyHeader
from pydantic import BaseModel

JWT_SECRET = os.environ.get("HOTPOT_JWT_SECRET", "hotpot-dev-secret-change-in-prod")
JWT_ALG = "HS256"
JWT_EXPIRE_HOURS = int(os.environ.get("HOTPOT_JWT_HOURS", "24"))
AUTH_MODE = os.environ.get("HOTPOT_AUTH_MODE", "demo")  # demo | strict

# Edge API keys (store-scoped writes)
DEFAULT_API_KEYS: Dict[str, str] = {
    "edge_yuhuan_dev_key": "store_yuhuan",
    "edge_jiaojiang_dev_key": "store_jiaojiang",
    "admin_seed_key": "*",
}

DEMO_USERS = {
    ("zhangdian", "demo"): {"role": "店长", "name": "张店长"},
    ("lingban", "demo"): {"role": "前厅领班", "name": "李领班"},
    ("chushi", "demo"): {"role": "厨师长", "name": "王厨师长"},
    ("shouhuo", "demo"): {"role": "收货员", "name": "赵收货"},
    ("quyududao", "demo"): {"role": "区域督导", "name": "区域督导", "store_id": "*"},
    ("zongbu", "demo"): {"role": "总部PMO", "name": "总部PMO", "store_id": "*"},
    ("laoban", "demo"): {"role": "集团决策者", "name": "冯老板", "store_id": "*"},
    ("banzu", "demo"): {"role": "班组长", "name": "孙班组长"},
    ("yingxiao", "demo"): {"role": "营销运营", "name": "周营销", "store_id": "*"},
    ("caiwu", "demo"): {"role": "财务审计", "name": "吴财审", "store_id": "*"},
}

bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-Api-Key", auto_error=False)


class TokenRequest(BaseModel):
    username: str
    password: str = "demo"
    store_id: str = "store_yuhuan"
    role: str = "店长"


class AuthContext(BaseModel):
    sub: str
    role: str
    store_id: str
    auth_type: str  # jwt | api_key | anonymous


def data_scope_for_role(role: str) -> str:
    if role in ("总部PMO", "总部 IT", "集团决策者", "营销运营", "财务审计"):
        return "national"
    if role == "区域督导":
        return "region"
    # 班组长 falls through to store scope (本店·本班组)
    return "store"


def can_admin(auth: AuthContext) -> bool:
    return auth.role in ("总部PMO", "总部 IT")


def enforce_admin(auth: AuthContext) -> None:
    if AUTH_MODE == "demo" and auth.auth_type == "anonymous":
        return
    if not can_admin(auth):
        raise HTTPException(status_code=403, detail="Admin access required")


def create_access_token(username: str, role: str, store_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "role": role,
        "store_id": store_id,
        "data_scope": data_scope_for_role(role),
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> AuthContext:
    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        return AuthContext(
            sub=data["sub"],
            role=data.get("role", "店长"),
            store_id=data.get("store_id", "store_yuhuan"),
            auth_type="jwt",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}") from exc


def login_user(req: TokenRequest) -> Dict[str, Any]:
    user = DEMO_USERS.get((req.username, req.password))
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    store_id = user.get("store_id") or req.store_id
    role = req.role or user["role"]
    if role == "区域督导":
        store_id = "*"
    if role in ("总部PMO", "总部 IT", "集团决策者", "营销运营", "财务审计"):
        store_id = "*"
    token = create_access_token(req.username, role, store_id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": JWT_EXPIRE_HOURS * 3600,
        "user": {
            "username": req.username,
            "name": user["name"],
            "role": role,
            "store_id": store_id,
            "data_scope": data_scope_for_role(role),
        },
    }


def resolve_api_key(key: Optional[str]) -> Optional[AuthContext]:
    if not key:
        return None
    store_id = DEFAULT_API_KEYS.get(key)
    if not store_id:
        return None
    return AuthContext(sub="edge", role="edge", store_id=store_id, auth_type="api_key")


def can_read_store(auth: AuthContext, store_id: str) -> bool:
    if auth.store_id == "*":
        return True
    if auth.role in ("区域督导", "集团决策者", "营销运营", "财务审计"):
        return True
    return auth.store_id == store_id


def can_write_store(auth: AuthContext, store_id: str) -> bool:
    if auth.auth_type == "api_key":
        return auth.store_id == "*" or auth.store_id == store_id
    # read-only / non-operational-write roles
    if auth.role in ("集团决策者", "营销运营", "财务审计"):
        return False
    if auth.role == "区域督导":
        return True
    # 班组长：本店写（任务 ack/reassign、桌态）；更细的"不可收货提交/Admin写"由
    # rbac.json actions + 端点级校验把关，此处只做门店级 scope 判定。
    if auth.role in ("店长", "厨师长", "前厅领班", "班组长", "edge"):
        return auth.store_id == "*" or auth.store_id == store_id
    if auth.role == "收货员":
        return auth.store_id == store_id
    return False


async def get_auth_context(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    api_key: Optional[str] = Depends(api_key_header),
) -> AuthContext:
    if api_key:
        ctx = resolve_api_key(api_key)
        if ctx:
            return ctx

    if creds and creds.credentials:
        return decode_token(creds.credentials)

    if AUTH_MODE == "demo":
        return AuthContext(sub="demo", role="店长", store_id="*", auth_type="anonymous")

    raise HTTPException(status_code=401, detail="Authentication required")


def enforce_store_read(auth: AuthContext, store_id: str) -> None:
    if AUTH_MODE == "demo" and auth.auth_type == "anonymous":
        return
    if not can_read_store(auth, store_id):
        raise HTTPException(status_code=403, detail=f"Forbidden for store {store_id}")


def enforce_store_write(auth: AuthContext, store_id: str) -> None:
    if AUTH_MODE == "demo" and auth.auth_type == "anonymous":
        return
    if not can_write_store(auth, store_id):
        raise HTTPException(status_code=403, detail=f"Write forbidden for store {store_id}")
