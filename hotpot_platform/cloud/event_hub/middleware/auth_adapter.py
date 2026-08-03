"""
火瞳统一认证适配器 (Auth Adapter)

用途: 在非FastAPI环境(http.server)中使用auth_unified.py

设计文档: docs/P1-B_身份统一_PIN转JWT方案设计_20260803.md

适用场景:
- Edge UI server_v2.py (http.server)
- 任何需要手动调用认证的Python代码

使用示例:
    from hotpot_platform.cloud.event_hub.middleware.auth_adapter import AuthAdapter

    adapter = AuthAdapter()

    # 在HTTP请求处理中验证Token
    def handle_request(self):
        token = self.headers.get("Authorization", "").replace("Bearer ", "")
        context = adapter.verify_token(token)
        if not context.authenticated:
            self.send_error(401, "未认证")
            return
        # 继续处理...
        username = context.username
"""

import json
import logging
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs

# 导入核心模块
from hotpot_platform.cloud.event_hub.middleware.auth_unified import (
    UnifiedAuthManager,
    AuthContext,
    TokenResponse,
    get_auth_manager,
    init_auth_manager,
)

logger = logging.getLogger("hotpot.auth.adapter")


class AuthAdapter:
    """
    认证适配器 - 桥接 auth_unified.py 和 HTTP Server

    提供简化的同步接口，隐藏async/await复杂性
    """

    def __init__(self, **kwargs):
        """
        初始化适配器

        Args:
            **kwargs: 传递给 UnifiedAuthManager 的参数
        """
        self.manager = UnifiedAuthManager(**kwargs)
        logger.info(f"AuthAdapter初始化完成: mode={self.manager.auth_mode}")

    # ── 同步包装方法 ──

    def jwt_login_sync(self, username: str, password: str, client_ip: str = "unknown") -> Dict[str, Any]:
        """
        同步JWT登录 (内部处理async)

        Returns:
            成功: {"ok": True, "token": "...", ...}
            失败: {"ok": False, "error": "...", "status_code": 401}
        """
        import asyncio

        try:
            loop = asyncio.new_event_loop()
            response = loop.run_until_complete(
                self.manager.jwt_login(username, password, client_ip)
            )
            loop.close()

            return {
                "ok": True,
                "access_token": response.access_token,
                "token_type": response.token_type,
                "expires_in": response.expires_in,
                "login_mode": response.login_mode,
                "user": response.user,
            }
        except Exception as e:
            status = getattr(e, 'status_code', 401)
            detail = getattr(e, 'detail', str(e))
            return {"ok": False, "error": detail, "status_code": status}

    def pin_login_sync(self, pin: str, client_ip: str = "unknown") -> Dict[str, Any]:
        """
        同步PIN登录 (内部处理async)

        Returns:
            同 jwt_login_sync
        """
        import asyncio

        try:
            loop = asyncio.new_event_loop()
            response = loop.run_until_complete(self.manager.pin_login(pin, client_ip))
            loop.close()

            return {
                "ok": True,
                "access_token": response.access_token,
                "token_type": response.token_type,
                "expires_in": response.expires_in,
                "login_mode": response.login_mode,
                "user": response.user,
            }
        except Exception as e:
            status = getattr(e, 'status_code', 401)
            detail = getattr(e, 'detail', str(e))
            return {"ok": False, "error": detail, "status_code": status}

    def verify_token_sync(self, token: Optional[str]) -> AuthContext:
        """同步Token验证"""
        return self.manager.verify_token(token)

    def refresh_token_sync(self, token: str) -> Dict[str, Any]:
        """同步Token刷新"""
        import asyncio

        try:
            loop = asyncio.new_event_loop()
            response = loop.run_until_complete(self.manager.refresh_token(token))
            loop.close()

            return {
                "ok": True,
                "access_token": response.access_token,
                "expires_in": response.expires_in,
                "login_mode": response.login_mode,
                "user": response.user,
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "status_code": 401}

    # ── HTTP请求辅助方法 ──

    def extract_token_from_request(self, headers: Dict[str, str], cookies: Dict[str, str] = None) -> Optional[str]:
        """
        从HTTP请求中提取Token

        优先级:
        1. Authorization: Bearer <token>
        2. Cookie: session_token
        3. Query Param: ?token=<token> (仅开发模式)
        """
        # Header
        auth_header = headers.get("Authorization", headers.get("authorization", ""))
        if auth_header.startswith("Bearer "):
            return auth_header[7:]

        # Cookie
        if cookies and "session_token" in cookies:
            return cookies["session_token"]

        # 开发模式Query参数
        import os
        if os.getenv("HOTPOT_DEV_MODE") == "true":
            # 从headers中提取query string (需要调用方传入)
            pass

        return None

    def authenticate_request(
        self,
        headers: Dict[str, str],
        cookies: Dict[str, str] = None,
        required: bool = True,
    ) -> Tuple[AuthContext, Optional[Dict[str, Any]]]:
        """
        验证HTTP请求的认证状态

        Args:
            headers: HTTP请求头字典
            cookies: Cookie字典 (可选)
            required: 是否要求必须认证 (False=允许匿名访问)

        Returns:
            (AuthContext, error_dict_or_None)
            - 如果认证成功: (context, None)
            - 如果认证失败且required=True: (unauth_context, error_dict)
            - 如果未认证且required=False: (guest_context, None)
        """
        token = self.extract_token_from_request(headers, cookies)
        context = self.verify_token_sync(token)

        if context.authenticated:
            return (context, None)

        if not required:
            return (AuthContext(authenticated=False), None)

        error = {
            "ok": False,
            "error": "未认证或Token已过期",
            "status_code": 401,
        }
        return (context, error)


# ── 全局单例 ──

_adapter_instance: Optional[AuthAdapter] = None


def get_auth_adapter(**kwargs) -> AuthAdapter:
    """获取全局认证适配器单例"""
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = AuthAdapter(**kwargs)
    return _adapter_instance


def init_auth_adapter(**kwargs) -> AuthAdapter:
    """初始化全局认证适配器"""
    global _adapter_instance
    _adapter_instance = AuthAdapter(**kwargs)
    logger.info(f"全局AuthAdapter已初始化")
    return _adapter_instance


# ── Edge UI 集成辅助函数 ──

def create_edge_ui_auth_handler(base_path: str = "/api/v1/auth"):
    """
    创建Edge UI认证API处理器 (用于http.server)

    返回一个路由字典: {path: handler_function}
    可在server_v2.py中注册到路由表

    用法:
        from hotpot_platform.cloud.event_hub.middleware.auth_adapter import create_edge_ui_auth_handler

        auth_routes = create_edge_ui_auth_handler()
        # 在do_GET/do_POST中:
        # if self.path in auth_routes:
        #     auth_routes[self.path](self)
    """
    adapter = get_auth_adapter()

    routes = {}

    def handle_jwt_login(handler):
        """POST /api/v1/auth/jwt-login"""
        content_length = int(handler.headers.get('Content-Length', 0))
        body = handler.rfile.read(content_length)
        data = json.loads(body) if body else {}

        result = adapter.jwt_login_sync(
            username=data.get("username", ""),
            password=data.get("password", ""),
            client_ip=handler.client_address[0] if handler.client_address else "unknown",
        )

        send_json_response(handler, result, status_code=200 if result["ok"] else 401)

    def handle_pin_login(handler):
        """POST /api/v1/auth/pin-login"""
        content_length = int(handler.headers.get('Content-Length', 0))
        body = handler.rfile.read(content_length)
        data = json.loads(body) if body else {}

        result = adapter.pin_login_sync(
            pin=data.get("pin", ""),
            client_ip=handler.client_address[0] if handler.client_address else "unknown",
        )

        send_json_response(handler, result, status_code=200 if result["ok"] else 401)

    def handle_refresh(handler):
        """POST /api/v1/auth/refresh"""
        content_length = int(handler.headers.get('Content-Length', 0))
        body = handler.rfile.read(content_length)
        data = json.loads(body) if body else {}

        result = adapter.refresh_token_sync(data.get("refresh_token", ""))
        send_json_response(handler, result, status_code=200 if result["ok"] else 401)

    def handle_logout(handler):
        """POST /api/v1/auth/logout"""
        result = {"ok": True, "message": "已登出"}
        send_json_response(handler, result)

    def handle_status(handler):
        """GET /api/v1/auth/status"""
        # 手动解析headers和cookies
        headers_dict = dict(handler.headers.items())
        cookie_header = headers_dict.get("Cookie", "")
        cookies = {}
        if cookie_header:
            for item in cookie_header.split(';'):
                item = item.strip()
                if '=' in item:
                    k, v = item.split('=', 1)
                    cookies[k.strip()] = v.strip()

        token = adapter.extract_token_from_request(headers_dict, cookies)
        context = adapter.verify_token_sync(token)

        send_json_response(handler, context.model_dump())

    # 注册路由
    routes.update({
        f"{base_path}/jwt-login": ("POST", handle_jwt_login),
        f"{base_path}/pin-login": ("POST", handle_pin_login),
        f"{base_path}/refresh": ("POST", handle_refresh),
        f"{base_path}/logout": ("POST", handle_logout),
        f"{base_path}/status": ("GET", handle_status),
    })

    return routes


def send_json_response(handler, data: Any, status_code: int = 200):
    """发送JSON响应 (用于http.server)"""
    body = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
    handler.send_response(status_code)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', len(body))
    # CORS headers (开发环境)
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.end_headers()
    handler.wfile.write(body)


# ── FastAPI 集成辅助函数 ──

def register_unified_auth_to_app(app):
    """
    将统一认证路由注册到FastAPI应用

    用法:
        from fastapi import FastAPI
        from hotpot_platform.cloud.event_hub.middleware.auth_adapter import register_unified_auth_to_app

        app = FastAPI()
        register_unified_auth_to_app(app)
    """
    from hotpot_platform.cloud.event_hub.middleware.auth_unified import unified_auth_router

    app.include_router(unified_auth_router)
    logger.info("统一认证路由已注册到FastAPI应用")

    # 初始化全局管理器
    init_auth_manager()
