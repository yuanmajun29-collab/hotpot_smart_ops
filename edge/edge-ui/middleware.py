"""
火瞳 Edge UI · Session 认证依赖 (Depends机制)

设计文档: §7 安全架构 (L2 访问控制)
- 使用 FastAPI Depends 机制保护 API 路由
- 验证 Cookie 中的 session_token
- 未认证请求返回 401 + {detail: "需要登录"}
- 支持滑动窗口刷新session超时

用法:
    from .middleware import get_current_session

    @router.get("/protected")
    async def protected_route(_=Depends(get_current_session)):
        ...
"""

from fastapi import Cookie, Depends, HTTPException, Request
from typing import Optional


async def get_current_session(
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
) -> dict:
    """
    验证当前请求的 session token

    Returns:
        dict: session 信息 (含 expires_at)

    Raises:
        HTTPException: 401 如果token无效或过期
    """
    from api.auth_api import verify_session, refresh_session

    if not verify_session(session_token):
        raise HTTPException(
            status_code=401,
            detail="需要登录",
            headers={"WWW-Authenticate": 'Session realm="Edge UI"'},
        )

    # 滑动窗口刷新超时
    if session_token:
        refresh_session(session_token)

    return {"token": session_token, "authenticated": True}
