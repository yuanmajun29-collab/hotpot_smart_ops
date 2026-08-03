"""
火瞳统一认证模块 (Unified Authentication Module)

设计文档: docs/P1-B_身份统一_PIN转JWT方案设计_20260803.md

核心功能:
1. 双模式登录: JWT (用户名密码) + PIN (6位数字) → 统一输出 JWT Bearer Token
2. PIN → JWT 透明转换: 保持Edge UI简洁性同时获得JWT的RBAC能力
3. 统一Token验证: 兼容Bearer Header + Cookie双通道提取
4. FastAPI依赖注入: get_current_auth() 可直接用于路由保护

架构位置:
  浏览器 → [PIN/JWT Login] → auth_unified.py → [JWT Token] → API Middleware → 业务逻辑

使用示例:
    from hotpot_platform.cloud.event_hub.middleware.auth_unified import (
        UnifiedAuthManager, get_current_auth, get_optional_auth
    )

    @router.get("/protected")
    async def protected_endpoint(auth: AuthContext = Depends(get_current_auth)):
        return {"user": auth.username, "role": auth.role}

    @router.get("/public")
    async def public_endpoint(auth: Optional[AuthContext] = Depends(get_optional_auth)):
        if auth:
            return {"greeting": f"你好, {auth.username}"}
        return {"message": "请先登录"}
"""

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from fastapi import Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator

# 尝试导入 PyJWT (Event Hub 已有依赖)
try:
    import jwt
    PYJWT_AVAILABLE = True
except ImportError:
    PYJWT_AVAILABLE = False
    logging.warning("PyJWT未安装，JWT功能将受限。请执行: pip install PyJWT")

# ── 日志配置 ──
logger = logging.getLogger("hotpot.auth.unified")

# ── 配置常量 ──

# JWT配置
JWT_SECRET_KEY = os.getenv("HOTPOT_JWT_SECRET", "hotpot-dev-secret-key-change-in-production-2026!")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("HOTPOT_JWT_HOURS", "24"))
JWT_ISSUER = "hotpot-platform"

# PIN配置
DEFAULT_PIN = os.getenv("HOTPOT_DEFAULT_PIN", "123456")
DEFAULT_USER = os.getenv("HOTPOT_DEFAULT_USER", "zhangdian")
DEFAULT_ROLE = os.getenv("HOTPOT_DEFAULT_ROLE", "店长")
DEFAULT_STORE_ID = os.getenv("HOTPOT_STORE_ID", "store_jiaojiang")

# 安全配置
MAX_LOGIN_ATTEMPTS = 5  # 最大登录尝试次数
LOCKOUT_DURATION = 300  # 锁定时长(秒), 5分钟

# 配置文件路径
CONFIG_DIR = Path(__file__).parent.parent.parent.parent / "edge" / "edge-ui" / "conf"
PIN_JWT_MAPPING_FILE = CONFIG_DIR / "pin_jwt_mapping.json"
PIN_STORE_FILE = CONFIG_DIR / "pin_store.json"

# ── 数据模型 ──


class AuthContext(BaseModel):
    """统一的认证上下文 (用于注入到请求中)"""

    authenticated: bool = False
    username: Optional[str] = None
    role: Optional[str] = None
    store_id: Optional[str] = None
    data_scope: List[str] = []
    token_type: str = "none"  # "jwt" | "pin" | "none"
    login_mode: str = "none"  # "jwt" | "pin" | "none"
    issued_at: Optional[int] = None
    expires_at: Optional[int] = None

    @property
    def is_admin(self) -> bool:
        """是否为管理员角色"""
        admin_roles = {"总部PMO", "集团决策者", "区域督导"}
        return self.role in admin_roles if self.role else False

    @property
    def can_manage_store(self) -> bool:
        """是否可管理门店 (管理员总是返回True)"""
        if self.is_admin:
            return True
        return len(self.data_scope) > 0 if self.data_scope else False

    def can_manage_specific_store(self, store_id: str) -> bool:
        """是否可管理指定门店"""
        if self.is_admin:
            return True
        return store_id in self.data_scope if self.data_scope else False


class TokenResponse(BaseModel):
    """Token响应 (登录成功后返回)"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # 秒
    login_mode: str  # "jwt" | "pin"
    user: Dict[str, Any]


class PinLoginRequest(BaseModel):
    """PIN登录请求"""

    pin: str = Field(..., min_length=6, max_length=6, description="6位数字PIN")

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("PIN必须为6位数字")
        return v


class JwtLoginRequest(BaseModel):
    """JWT登录请求"""

    username: str = Field(..., min_length=2, max_length=50, description="用户名")
    password: str = Field(..., min_length=1, max_length=100, description="密码")


class RefreshTokenRequest(BaseModel):
    """刷新Token请求"""

    refresh_token: str = Field(..., description="Refresh Token")


class PinJwtMapping(BaseModel):
    """PIN→JWT映射配置"""

    default_pin: str = DEFAULT_PIN
    default_user: str = DEFAULT_USER
    default_role: str = DEFAULT_ROLE
    mappings: Dict[str, Dict[str, str]] = {}
    allow_custom_pin: bool = True


# ── 内置Demo用户 (复用 Event Hub auth.py 的定义) ──

DEMO_USERS: Dict[str, Dict[str, Any]] = {
    "zhangdian": {
        "password": "demo",
        "role": "店长",
        "name": "张店",
        "data_scope": ["store_jiaojiang"],
    },
    "chushi": {
        "password": "demo",
        "role": "厨师长",
        "name": "潘厨",
        "data_scope": ["store_jiaojiang"],
    },
    "lingban": {
        "password": "demo",
        "role": "前厅领班",
        "name": "李领",
        "data_scope": ["store_jiaojiang"],
    },
    "shouhuo": {
        "password": "demo",
        "role": "收货员",
        "name": "王货",
        "data_scope": ["store_jiaojiang"],
    },
    "quyududao": {
        "password": "demo",
        "role": "区域督导",
        "name": "赵督",
        "data_scope": ["*"],  # 全部门店
    },
    "zongbu": {
        "password": "demo",
        "role": "总部PMO",
        "name": "钱总",
        "data_scope": ["*"],  # 全部门店
    },
    "laoban": {
        "password": "demo",
        "role": "集团决策者",
        "name": "孙董",
        "data_scope": ["*"],  # 全部门店
    },
}


# ── 登录尝试记录 (防暴力破解) ──

_login_attempts: Dict[str, List[float]] = {}  # {ip_or_identifier: [timestamp1, timestamp2, ...]}


def _check_rate_limit(identifier: str) -> bool:
    """检查是否触发速率限制"""
    now = time.time()
    attempts = _login_attempts.get(identifier, [])

    # 清理5分钟前的记录
    recent = [t for t in attempts if now - t < LOCKOUT_DURATION]
    _login_attempts[identifier] = recent

    if len(recent) >= MAX_LOGIN_ATTEMPTS:
        logger.warning(f"登录频率限制触发: identifier={identifier}, attempts={len(recent)}")
        return False

    return True


def _record_attempt(identifier: str) -> None:
    """记录一次登录尝试"""
    _login_attempts.setdefault(identifier, []).append(time.time())


# ── 核心类: UnifiedAuthManager ──


class UnifiedAuthManager:
    """
    统一认证管理器 (PIN + JWT 双模式)

    设计原则:
    - 以 Event Hub JWT 为标准 (已有完整RBAC实现)
    - Edge UI PIN 平滑迁移到 JWT (透明转换)
    - 双模式过渡期支持 (可配置切换)

    使用方式:
        manager = UnifiedAuthManager()
        response = await manager.jwt_login("zhangdian", "demo")
        response = await manager.pin_login("123456")
        context = manager.verify_token(token)
    """

    def __init__(
        self,
        secret_key: str = JWT_SECRET_KEY,
        expire_hours: int = JWT_EXPIRE_HOURS,
        store_id: str = DEFAULT_STORE_ID,
        auth_mode: str = "dual",  # "jwt" | "pin" | "dual"
    ):
        """
        初始化统一认证管理器

        Args:
            secret_key: JWT签名密钥 (生产环境≥256bit)
            expire_hours: Token过期时间(小时)
            store_id: 默认门店ID
            auth_mode: 认证模式 ("jwt"|"pin"|"dual")
        """
        self.secret_key = secret_key
        self.expire_hours = expire_hours
        self.store_id = store_id
        self.auth_mode = auth_mode

        # 加载PIN→JWT映射配置
        self.pin_mapping = self._load_pin_mapping()

        # 验证PyJWT可用性
        if not PYJWT_AVAILABLE and auth_mode in ("jwt", "dual"):
            logger.error("PyJWT未安装，无法使用JWT模式")

        logger.info(
            f"UnifiedAuthManager初始化完成: mode={auth_mode}, "
            f"expire={expire_hours}h, store={store_id}"
        )

    # ── 配置加载 ──

    def _load_pin_mapping(self) -> PinJwtMapping:
        """加载PIN→JWT映射配置"""
        try:
            if PIN_JWT_MAPPING_FILE.exists():
                data = json.loads(PIN_JWT_MAPPING_FILE.read_text())
                return PinJwtMapping(**data)
        except Exception as e:
            logger.warning(f"加载PIN映射配置失败: {e}, 使用默认值")

        # 默认映射
        return PinJwtMapping(
            mappings={
                "123456": {"username": "zhangdian", "role": "店长"},
                "654321": {"username": "chushi", "role": "厨师长"},
                "111111": {"username": "quyududao", "role": "区域督导"},
            }
        )

    def _save_pin_mapping(self, mapping: PinJwtMapping) -> None:
        """保存PIN→JWT映射配置"""
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            PIN_JWT_MAPPING_FILE.write_text(mapping.model_dump_json(indent=2))
        except Exception as e:
            logger.error(f"保存PIN映射配置失败: {e}")

    # ── PIN 工具函数 (从 auth_api.py 迁移) ──

    @staticmethod
    def _hash_pin(pin: str) -> str:
        """PIN哈希: SHA256(salt + pin)"""
        salt = "hotpot_edge_ui_v1"
        return hashlib.sha256(f"{salt}{pin}".encode()).hexdigest()

    def _verify_stored_pin(self, pin: str) -> bool:
        """验证PIN与存储的hash是否匹配"""
        try:
            if PIN_STORE_FILE.exists():
                store = json.loads(PIN_STORE_FILE.read_text())
                stored_hash = store.get("pin_hash")
                if stored_hash:
                    return self._hash_pin(pin) == stored_hash
        except Exception as e:
            logger.warning(f"验证PIN失败: {e}")
        return False

    def _is_pin_setup(self) -> bool:
        """检查PIN是否已初始化"""
        try:
            if PIN_STORE_FILE.exists():
                store = json.loads(PIN_STORE_FILE.read_text())
                return store.get("setup_completed", False)
        except Exception:
            pass
        return False

    # ── JWT Token 生成/验证 ──

    def _create_jwt_token(
        self,
        username: str,
        role: str,
        store_id: str = None,
        data_scope: List[str] = None,
        extra_claims: Dict[str, Any] = None,
    ) -> str:
        """
        创建JWT Token

        Args:
            username: 用户名
            role: 角色
            store_id: 门店ID (默认使用实例配置)
            data_scope: 数据范围列表
            extra_claims: 额外的claims

        Returns:
            编码后的JWT字符串
        """
        if not PYJWT_AVAILABLE:
            raise RuntimeError("PyJWT未安装，无法生成JWT Token")

        now = datetime.now(tz=timezone.utc)
        expire = now + timedelta(hours=self.expire_hours)

        payload = {
            "sub": username,
            "role": role,
            "store_id": store_id or self.store_id,
            "data_scope": data_scope or [self.store_id],
            "iat": int(now.timestamp()),
            "exp": int(expire.timestamp()),
            "iss": JWT_ISSUER,
            "jti": hashlib.sha256(os.urandom(16)).hexdigest()[:16],  # 唯一ID
        }

        if extra_claims:
            payload.update(extra_claims)

        token = jwt.encode(payload, self.secret_key, algorithm=JWT_ALGORITHM)
        logger.debug(f"JWT Token已生成: user={username}, role={role}, exp={expire.isoformat()}")
        return token

    def _decode_jwt_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        解码并验证JWT Token

        Returns:
            解码后的payload, 如果无效返回None
        """
        if not PYJWT_AVAILABLE:
            return None

        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[JWT_ALGORITHM],
                issuer=JWT_ISSUER,
                options={"require": ["sub", "exp", "iat"]},
            )
            return payload
        except jwt.ExpiredSignatureError:
            logger.debug("JWT Token已过期")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"JWT Token无效: {e}")
            return None

    # ── 登录方法 ──

    async def jwt_login(self, username: str, password: str, request_ip: str = "unknown") -> TokenResponse:
        """
        JWT模式登录 (用户名+密码)

        复用 Event Hub auth.py 的 Demo 用户库

        Args:
            username: 用户名
            password: 密码
            request_ip: 请求IP (用于限流)

        Returns:
            TokenResponse (包含access_token和用户信息)

        Raises:
            HTTPException: 认证失败时抛出401
        """
        # 检查认证模式
        if self.auth_mode == "pin":
            raise HTTPException(status_code=403, detail="当前仅支持PIN模式登录")

        # 速率限制检查
        if not _check_rate_limit(request_ip):
            raise HTTPException(status_code=429, detail=f"登录尝试次数过多，请{LOCKOUT_DURATION//60}分钟后重试")

        # 验证用户凭据
        user_info = DEMO_USERS.get(username)
        if not user_info or user_info["password"] != password:
            _record_attempt(request_ip)
            logger.warning(f"JWT登录失败: user={username}, ip={request_ip}")
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        # 生成JWT Token
        token = self._create_jwt_token(
            username=username,
            role=user_info["role"],
            data_scope=user_info.get("data_scope", [self.store_id]),
            extra_claims={"login_mode": "jwt", "name": user_info.get("name", username)},
        )

        # 清除该IP的失败计数
        _login_attempts.pop(request_ip, None)

        return TokenResponse(
            access_token=token,
            token_type="bearer",
            expires_in=self.expire_hours * 3600,
            login_mode="jwt",
            user={
                "username": username,
                "name": user_info.get("name", username),
                "role": user_info["role"],
                "store_id": self.store_id,
                "data_scope": user_info.get("data_scope", [self.store_id]),
            },
        )

    async def pin_login(self, pin: str, request_ip: str = "unknown") -> TokenResponse:
        """
        PIN模式登录 (6位数字) → 内部转换为JWT

        流程:
        1. 验证PIN格式 (6位数字)
        2. 速率限制检查
        3. PIN哈希比对 (优先使用pin_store.json)
        4. 查找PIN→用户映射
        5. 生成JWT Token (与jwt_login输出一致)

        Args:
            pin: 6位数字PIN
            request_ip: 请求IP (用于限流)

        Returns:
            TokenResponse (包含JWT Token)

        Raises:
            HTTPException: PIN错误或锁定时抛出401/429
        """
        # 检查认证模式
        if self.auth_mode == "jwt":
            raise HTTPException(status_code=403, detail="当前仅支持账号密码登录")

        # 速率限制检查
        if not _check_rate_limit(request_ip):
            raise HTTPException(status_code=429, detail=f"登录尝试次数过多，请{LOCKOUT_DURATION//60}分钟后重试")

        # 验证PIN
        pin_valid = False

        # 方式1: 与存储的PIN hash比对 (如果已设置)
        if self._is_pin_setup():
            if self._verify_stored_pin(pin):
                pin_valid = True

        # 方式2: 与默认PIN或映射表比对
        if not pin_valid:
            if pin == self.pin_mapping.default_pin:
                pin_valid = True
            elif pin in self.pin_mapping.mappings:
                pin_valid = True

        if not pin_valid:
            _record_attempt(request_ip)
            logger.warning(f"PIN登录失败: ip={request_ip}")
            raise HTTPException(status_code=401, detail="PIN错误")

        # 查找映射的用户信息
        user_info = self.pin_mapping.mappings.get(pin)
        if not user_info:
            # 使用默认用户
            user_info = {
                "username": self.pin_mapping.default_user,
                "role": self.pin_mapping.default_role,
            }

        username = user_info["username"]
        role = user_info["role"]

        # 生成JWT Token (标记来源为PIN)
        token = self._create_jwt_token(
            username=username,
            role=role,
            extra_claims={
                "login_mode": "pin",
                "name": username,
                "pin_authenticated": True,  # 标记PIN来源
            },
        )

        # 清除失败计数
        _login_attempts.pop(request_ip, None)

        logger.info(f"PIN登录成功: user={username}, role={role}, ip={request_ip}")

        return TokenResponse(
            access_token=token,
            token_type="bearer",
            expires_in=self.expire_hours * 3600,
            login_mode="pin",
            user={
                "username": username,
                "name": username,
                "role": role,
                "store_id": self.store_id,
                "data_scope": [self.store_id],
            },
        )

    # ── Token 验证 ──

    def verify_token(self, token: str) -> AuthContext:
        """
        统一Token验证入口

        支持两种格式:
        1. JWT Bearer Token (标准)
        2. PIN Session Token (兼容, 过渡期使用)

        Args:
            token: Token字符串

        Returns:
            AuthContext (包含用户信息和权限)
        """
        if not token:
            return AuthContext(authenticated=False)

        # 方式1: 尝试JWT解码
        payload = self._decode_jwt_token(token)
        if payload:
            return AuthContext(
                authenticated=True,
                username=payload.get("sub"),
                role=payload.get("role"),
                store_id=payload.get("store_id"),
                data_scope=payload.get("data_scope", []),
                token_type="jwt",
                login_mode=payload.get("login_mode", "jwt"),
                issued_at=payload.get("iat"),
                expires_at=payload.get("exp"),
            )

        # 方式2: PIN Session Token (兼容旧版)
        # 注意: 此处不实现完整的session验证，
        # 因为新系统应统一使用JWT。保留此注释作为扩展点。
        logger.debug(f"Token非有效JWT格式: {token[:20]}...")

        return AuthContext(authenticated=False)

    # ── FastAPI 依赖注入 ──

    def get_current_auth(
        self,
        request: Request,
        credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer(auto_error=False)),
    ) -> AuthContext:
        """
        统一认证依赖 (强制认证)

        用法:
            @router.get("/protected")
            async def endpoint(auth: AuthContext = Depends(manager.get_current_auth)):
                ...

        提取顺序:
        1. Authorization: Bearer <token> (Header)
        2. Cookie: session_token (兼容旧PIN)
        3. Query Param: token (开发调试用)

        未认证时抛出 401
        """
        token = None

        # 优先从Header获取
        if credentials and credentials.credentials:
            token = credentials.credentials

        # 其次从Cookie获取 (兼容旧PIN session)
        if not token:
            token = request.cookies.get("session_token")

        # 最后从Query参数获取 (仅开发环境)
        if not token and os.getenv("HOTPOT_DEV_MODE") == "true":
            token = request.query_params.get("token")

        # 验证Token
        context = self.verify_token(token) if token else AuthContext(authenticated=False)

        if not context.authenticated:
            raise HTTPException(
                status_code=401,
                detail="未认证或Token已过期，请重新登录",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 注入到request.state (供后续中间件使用)
        request.state.auth = context

        return context

    def get_optional_auth(
        self,
        request: Request,
        credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer(auto_error=False)),
    ) -> AuthContext:
        """
        可选认证依赖 (不强制登录)

        用法:
            @router.get("/public")
            async def endpoint(auth: AuthContext = Depends(manager.get_optional_auth)):
                if auth.authenticated:
                    return {"user": auth.username}
                return {"message": "匿名访问"}

        无论是否登录都返回AuthContext (authenticated可能为False)
        """
        token = None

        if credentials and credentials.credentials:
            token = credentials.credentials
        elif not token:
            token = request.cookies.get("session_token")

        context = self.verify_token(token) if token else AuthContext(authenticated=False)
        request.state.auth = context
        return context

    # ── Token 刷新 ──

    async def refresh_token(self, token: str) -> TokenResponse:
        """
        刷新Token (续期)

        验证旧Token有效性，签发新的Token (延长过期时间)

        Args:
            token: 当前有效的Token

        Returns:
            新的TokenResponse
        """
        context = self.verify_token(token)

        if not context.authenticated:
            raise HTTPException(status_code=401, detail="无效或已过期的Token")

        if not context.username or not context.role:
            raise HTTPException(status_code=401, detail="Token缺少必要信息")

        # 签发新Token
        new_token = self._create_jwt_token(
            username=context.username,
            role=context.role,
            store_id=context.store_id,
            data_scope=context.data_scope,
            extra_claims={"login_mode": context.login_mode, "refreshed": True},
        )

        return TokenResponse(
            access_token=new_token,
            token_type="bearer",
            expires_in=self.expire_hours * 3600,
            login_mode=context.login_mode or "jwt",
            user={
                "username": context.username,
                "role": context.role,
                "store_id": context.store_id,
                "data_scope": context.data_scope,
            },
        )


# ── 全局单例 ──

_manager_instance: Optional[UnifiedAuthManager] = None


def get_auth_manager() -> UnifiedAuthManager:
    """获取全局认证管理器单例"""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = UnifiedAuthManager()
    return _manager_instance


def init_auth_manager(**kwargs) -> UnifiedAuthManager:
    """
    初始化全局认证管理器 (应用启动时调用)

    用法:
        from hotpot_platform.cloud.event_hub.middleware.auth_unified import init_auth_manager

        app = FastAPI()
        manager = init_auth_manager(
            secret_key="your-secret-key",
            expire_hours=12,
            auth_mode="dual"
        )
    """
    global _manager_instance
    _manager_instance = UnifiedAuthManager(**kwargs)
    logger.info(f"全局认证管理器已初始化: {_manager_instance.auth_mode}模式")
    return _manager_instance


# ── 便捷依赖函数 (可直接在路由中使用) ──

async def _get_current_auth_dependency(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer(auto_error=False)),
) -> AuthContext:
    """内部函数: 获取当前认证状态 (强制)"""
    manager = get_auth_manager()
    return manager.get_current_auth(request, credentials)


async def _get_optional_auth_dependency(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer(auto_error=False)),
) -> AuthContext:
    """内部函数: 获取当前认证状态 (可选)"""
    manager = get_auth_manager()
    return manager.get_optional_auth(request, credentials)


# 导出给FastAPI路由使用的依赖
get_current_auth = _get_current_auth_dependency
get_optional_auth = _get_optional_auth_dependency


# ── API Router (统一认证端点) ──

from fastapi import APIRouter

unified_auth_router = APIRouter(prefix="/api/v1/auth", tags=["统一认证"])


@unified_auth_router.post("/jwt-login", response_model=TokenResponse)
async def jwt_login_endpoint(req: JwtLoginRequest, request: Request):
    """
    JWT模式登录 (用户名+密码)

    输入:
    {
        "username": "zhangdian",
        "password": "demo"
    }

    输出:
    {
        "access_token": "eyJhbGciOiJIUzI1NiJ9...",
        "token_type": "bearer",
        "expires_in": 86400,
        "login_mode": "jwt",
        "user": {...}
    }
    """
    manager = get_auth_manager()
    client_ip = request.client.host if request.client else "unknown"
    return await manager.jwt_login(req.username, req.password, client_ip)


@unified_auth_router.post("/pin-login", response_model=TokenResponse)
async def pin_login_endpoint(req: PinLoginRequest, request: Request):
    """
    PIN模式登录 (6位数字) → 自动转换为JWT

    输入:
    {
        "pin": "123456"
    }

    输出: 同jwt_login (login_mode="pin")
    """
    manager = get_auth_manager()
    client_ip = request.client.host if request.client else "unknown"
    return await manager.pin_login(req.pin, client_ip)


@unified_auth_router.post("/refresh", response_model=TokenResponse)
async def refresh_token_endpoint(req: RefreshTokenRequest):
    """
    刷新Token (续期)

    输入:
    {
        "refresh_token": "eyJhbGciOiJIUzI1NiJ9..."
    }

    输出: 新的TokenResponse (延长过期时间)
    """
    manager = get_auth_manager()
    return await manager.refresh_token(req.refresh_token)


@unified_auth_router.post("/logout")
async def logout_endpoint(response: Response):
    """
    登出

    操作:
    - 清除 session_token Cookie
    - 客户端应丢弃本地存储的JWT

    注意: JWT是无状态的，服务端无法主动使其失效。
    生产环境可引入Redis黑名单机制。
    """
    response.delete_cookie(key="session_token")
    return {"ok": True, "message": "已登出"}


@unified_auth_router.get("/status", response_model=AuthContext)
async def auth_status_endpoint(request: Request):
    """
    获取当前认证状态 (无需认证即可调用)

    返回当前用户的AuthContext (如未登录则authenticated=false)
    """
    manager = get_auth_manager()
    credentials = HTTPAuthorizationCredentials(auto_error=False)

    # 手动提取token
    auth_header = request.headers.get("authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    elif "session_token" in request.cookies:
        token = request.cookies["session_token"]

    context = manager.verify_token(token) if token else AuthContext(authenticated=False)
    return context
