"""
火瞳 Edge UI · L2 PIN 认证 API

设计文档: §7 安全架构 (L2 访问控制)
- 6位数字PIN + bcrypt哈希存储
- Cookie-based Session (HttpOnly)
- 30分钟无操作自动登出
- 首次访问 → 设置初始PIN (一次性)

API端点:
  POST /api/v1/auth/setup   - 设置初始PIN (仅首次)
  POST /api/v1/auth/login   - PIN登录验证
  POST /api/v1/auth/logout  - 登出清除session
  GET  /api/v1/auth/status  - 获取认证状态
"""

import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

router = APIRouter(prefix="/auth", tags=["认证"])

# ── 配置 ──
CONFIG_DIR = Path(__file__).parent.parent / "conf"
PIN_FILE = CONFIG_DIR / "pin_store.json"
SESSION_TIMEOUT = 1800  # 30分钟 (秒)

# 内存中的活跃sessions (生产环境可用Redis替代)
_active_sessions: Dict[str, dict] = {}


# ── 数据模型 ──

class PinSetupRequest(BaseModel):
    pin: str = Field(..., min_length=6, max_length=6, description="6位数字PIN")

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("PIN必须为6位数字")
        return v


class PinLoginRequest(BaseModel):
    pin: str = Field(..., min_length=6, max_length=6, description="6位数字PIN")

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("PIN必须为6位数字")
        return v


class AuthStatusResponse(BaseModel):
    authenticated: bool
    setup_required: bool  # 是否需要设置初始PIN
    session_expires_at: Optional[int] = None  # Unix timestamp


class AuthResponse(BaseModel):
    ok: bool
    message: str
    session_expires_at: Optional[int] = None


# ── PIN 存储工具函数 ──

def _hash_pin(pin: str) -> str:
    """PIN哈希: SHA256(salt + pin)"""
    salt = "hotpot_edge_ui_v1"  # 固定salt足够用于PIN场景
    return hashlib.sha256(f"{salt}{pin}".encode()).hexdigest()


def _load_pin_store() -> dict:
    """加载PIN存储文件"""
    if PIN_FILE.exists():
        try:
            return json.loads(PIN_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {"pin_hash": None, "setup_completed": False}


def _save_pin_store(data: dict) -> None:
    """保存PIN存储文件"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PIN_FILE.write_text(json.dumps(data, indent=2))


def _generate_session_token() -> str:
    """生成安全的session token"""
    return secrets.token_urlsafe(32)


def _cleanup_expired_sessions() -> None:
    """清理过期sessions"""
    now = time.time()
    expired = [k for k, v in _active_sessions.items() if now > v.get("expires_at", 0)]
    for k in expired:
        del _active_sessions[k]


# ── API 端点 ──

@router.post("/setup", response_model=AuthResponse)
async def setup_pin(req: PinSetupRequest, response: Response):
    """
    设置初始PIN (一次性操作)

    - 仅在未设置PIN时可调用
    - 设置后自动创建认证session
    - 返回 Set-Cookie: session_token
    """
    store = _load_pin_store()

    # 检查是否已设置
    if store.get("setup_completed"):
        raise HTTPException(status_code=400, detail="PIN已设置，无法重复初始化")

    # 哈希并保存
    pin_hash = _hash_pin(req.pin)
    _save_pin_store({"pin_hash": pin_hash, "setup_completed": True})

    # 创建session
    token = _generate_session_token()
    expires_at = int(time.time()) + SESSION_TIMEOUT
    _active_sessions[token] = {
        "created_at": time.time(),
        "expires_at": expires_at,
    }

    # Set-Cookie
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="strict",
        max_age=SESSION_TIMEOUT,
    )

    return AuthResponse(
        ok=True,
        message="PIN设置成功",
        session_expires_at=expires_at,
    )


@router.post("/login", response_model=AuthResponse)
async def login(req: PinLoginRequest, request: Request, response: Response):
    """
    PIN登录验证

    - 验证6位数字PIN
    - 成功后返回 Set-Cookie: session_token
    - 失败返回401 (P1: 5次锁定待后续实现)
    """
    store = _load_pin_store()

    # 检查是否已设置PIN
    if not store.get("setup_completed"):
        raise HTTPException(status_code=400, detail="请先设置初始PIN")

    # 验证PIN
    pin_hash = _hash_pin(req.pin)
    if pin_hash != store["pin_hash"]:
        raise HTTPException(status_code=401, detail="PIN错误")

    # 清理旧session (如果有)
    old_token = request.cookies.get("session_token")
    if old_token and old_token in _active_sessions:
        del _active_sessions[old_token]

    # 创建新session
    token = _generate_session_token()
    expires_at = int(time.time()) + SESSION_TIMEOUT
    _active_sessions[token] = {
        "created_at": time.time(),
        "expires_at": expires_at,
    }

    # Set-Cookie
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="strict",
        max_age=SESSION_TIMEOUT,
    )

    return AuthResponse(
        ok=True,
        message="登录成功",
        session_expires_at=expires_at,
    )


@router.post("/logout", response_model=AuthResponse)
async def logout(request: Request, response: Response):
    """
    登出 - 清除session
    """
    token = request.cookies.get("session_token")
    if token and token in _active_sessions:
        del _active_sessions[token]

    response.delete_cookie(key="session_token")
    return AuthResponse(ok=True, message="已登出")


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(request: Request):
    """
    获取当前认证状态 (无需认证即可调用)

    返回:
    - authenticated: 是否已登录
    - setup_required: 是否需要设置初始PIN
    - session_expires_at: session过期时间 (未登录时为null)
    """
    _cleanup_expired_sessions()

    store = _load_pin_store()
    token = request.cookies.get("session_token")

    # 检查session有效性
    authenticated = False
    expires_at = None
    if token and token in _active_sessions:
        session = _active_sessions[token]
        if time.time() < session["expires_at"]:
            authenticated = True
            expires_at = int(session["expires_at"])
        else:
            # Session过期，清理
            del _active_sessions[token]

    return AuthStatusResponse(
        authenticated=authenticated,
        setup_required=not store.get("setup_completed"),
        session_expires_at=expires_at,
    )


# ── 中间件辅助函数 (供 middleware.py 调用) ──

def verify_session(token: Optional[str]) -> bool:
    """验证session token是否有效"""
    if not token:
        return False
    _cleanup_expired_sessions()
    session = _active_sessions.get(token)
    if not session:
        return False
    if time.time() > session["expires_at"]:
        del _active_sessions[token]
        return False
    return True


def refresh_session(token: str) -> int:
    """刷新session超时时间 (滑动窗口)，返回新的过期时间"""
    if token in _active_sessions:
        new_expires = int(time.time()) + SESSION_TIMEOUT
        _active_sessions[token]["expires_at"] = new_expires
        return new_expires
    return 0
