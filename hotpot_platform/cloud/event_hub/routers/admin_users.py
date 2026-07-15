#!/usr/bin/env python3
"""RBAC 用户管理 API — 扩展已有 auth 系统

端点:
  GET  /v1/admin/users    — 用户列表
  POST /v1/admin/users    — 添加用户
  DELETE /v1/admin/users  — 删除用户
"""

import copy
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from hotpot_platform.cloud.event_hub.auth import (
    DEMO_USERS,
    get_auth_context,
    AuthContext,
    enforce_admin,
    login_user,
)
from hotpot_platform.cloud.event_hub.rbac import ROLE_POLICIES

router = APIRouter(prefix="/v1/admin", tags=["admin"])

ROLE_NAMES = list(ROLE_POLICIES.keys())


class UserAddBody(BaseModel):
    username: str
    password: str = "demo"
    role: str
    name: str = ""
    store_id: str = "store_yuhuan"
    stores: List[str] = []


class UserDeleteBody(BaseModel):
    username: str


@router.get("/users")
async def list_users(request: Request, auth: AuthContext = Depends(get_auth_context)):
    enforce_admin(auth)
    users = []
    for (username, pw), info in DEMO_USERS.items():
        users.append({
            "username": username,
            "role": info["role"],
            "name": info.get("name", username),
            "store_id": info.get("store_id", ""),
        })
    return {"users": users, "available_roles": ROLE_NAMES}


@router.post("/users")
async def add_user(body: UserAddBody, auth: AuthContext = Depends(get_auth_context)):
    enforce_admin(auth)
    key = (body.username, body.password)
    if key in DEMO_USERS:
        raise HTTPException(400, f"用户 {body.username} 已存在")
    DEMO_USERS[key] = {
        "role": body.role,
        "name": body.name or body.username,
    }
    if body.stores:
        DEMO_USERS[key]["store_id"] = body.stores[0]
    elif body.store_id:
        DEMO_USERS[key]["store_id"] = body.store_id
    return {"status": "ok", "username": body.username, "role": body.role}


@router.delete("/users")
async def delete_user(body: UserDeleteBody, auth: AuthContext = Depends(get_auth_context)):
    enforce_admin(auth)
    found = None
    for (u, p) in list(DEMO_USERS.keys()):
        if u == body.username:
            found = (u, p)
            break
    if not found:
        raise HTTPException(404, f"用户 {body.username} 不存在")
    del DEMO_USERS[found]
    return {"status": "ok", "username": body.username}
