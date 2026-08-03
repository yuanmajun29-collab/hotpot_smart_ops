"""
Event Hub 统一认证集成 (FastAPI)

使用方式:
    在 app.py 中添加:

        from hotpot_platform.cloud.event_hub.middleware.event_hub_auth_integration import register_auth

        # 在app创建后调用
        register_auth(app)
"""

from fastapi import FastAPI
import logging

logger = logging.getLogger("hotpot.auth.hub")


def register_auth(app: FastAPI):
    """
    将统一认证模块注册到Event Hub

    新增端点:
    - POST /api/v1/auth/jwt-login  - JWT登录
    - POST /api/v1/auth/pin-login   - PIN登录
    - POST /api/v1/auth/refresh     - Token刷新
    - POST /api/v1/auth/logout      - 登出
    - GET  /api/v1/auth/status      - 认证状态

    Args:
        app: FastAPI应用实例
    """
    from hotpot_platform.cloud.event_hub.middleware.auth_adapter import register_unified_auth_to_app

    # 注册统一认证路由
    register_unified_auth_to_app(app)

    # 添加CORS中间件 (开发环境)
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 生产环境应限制为具体域名
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    logger.info("✅ Event Hub统一认证已注册 (5个端点)")


# ── 认证依赖快捷导入 ──

def get_auth_dependencies():
    """获取统一认证依赖 (用于路由保护)"""
    from hotpot_platform.cloud.event_hub.middleware.auth_unified import (
        get_current_auth,
        get_optional_auth,
    )
    return {
        "current_auth": get_current_auth,
        "optional_auth": get_optional_auth,
    }


# ── 使用示例 ──

AUTH_USAGE_EXAMPLE = '''
# ══════════════════════════════════════════════════
# Event Hub 路由保护示例
# ══════════════════════════════════════════════════

from fastapi import APIRouter, Depends
from hotpot_platform.cloud.event_hub.middleware.auth_unified import (
    AuthContext, get_current_auth, get_optional_auth
)

router = APIRouter(prefix="/api/v1/demo", tags=["示例"])

@router.get("/public")
async def public_endpoint(auth: AuthContext = Depends(get_optional_auth)):
    """公开接口 (可选认证)"""
    if auth.authenticated:
        return {"message": f"你好, {auth.username}!"}
    return {"message": "你好, 匿名用户!"}

@router.get("/protected")
async def protected_endpoint(auth: AuthContext = Depends(get_current_auth)):
    """受保护接口 (必须登录)"""
    return {
        "user": auth.username,
        "role": auth.role,
        "store_id": auth.store_id,
    }

@router.get("/admin-only")
async def admin_endpoint(auth: AuthContext = Depends(get_current_auth)):
    """仅管理员"""
    if not auth.is_admin:
        raise HTTPException(403, "需要管理员权限")
    return {"message": "欢迎, 管理员!"}
'''
