"""
Edge UI 统一认证集成补丁

使用方式:
    在 server_v2.py 的 do_GET/do_POST 方法中添加:

        # 文件顶部导入
        from hotpot_platform.cloud.event_hub.middleware.auth_adapter import (
            get_auth_adapter, create_edge_ui_auth_handler, authenticate_request
        )

        # init_config() 之后初始化认证
        from hotpot_platform.cloud.event_hub.middleware.auth_adapter import init_auth_adapter
        init_auth_adapter(auth_mode="dual")

        # do_POST方法中添加路由分发
        def do_POST(self):
            # 认证路由
            auth_routes = create_edge_ui_auth_handler()
            if self.path in auth_routes:
                method, handler = auth_routes[self.path]
                if method == "POST":
                    handler(self)
                    return

            # ... 原有逻辑 ...
"""

# ── 集成代码片段 (可直接复制到server_v2.py) ──

EDGE_UI_AUTH_INTEGRATION = '''
# ══════════════════════════════════════════════════
# 统一认证模块 (P1-B 身份统一)
# ══════════════════════════════════════════════════

# 在文件头部导入区添加:
from hotpot_platform.cloud.event_hub.middleware.auth_adapter import (
    init_auth_adapter,
    get_auth_adapter,
    create_edge_ui_auth_handler,
    authenticate_request,
)

# 在init_config()函数末尾添加:
def _init_auth():
    """初始化统一认证模块"""
    global _auth_adapter
    _auth_adapter = init_auth_adapter(
        auth_mode="dual",  # 双模式: PIN + JWT
        store_id=_config_manager.get("store_id", os.environ.get("HOTPOT_STORE_ID", "")) if _config_manager else os.environ.get("HOTPOT_STORE_ID", ""),
    )
    print("[Auth] ✅ 统一认证模块已初始化 (PIN+JWT双模式)")

# 在do_POST()方法中添加 (在现有路由判断之前):
_AUTH_ROUTES = None

def _get_auth_routes():
    global _AUTH_ROUTES
    if _AUTH_ROUTES is None:
        _AUTH_ROUTES = create_edge_ui_auth_handler()
    return _AUTH_ROUTES

# 在do_POST()开头添加:
def do_POST(self):
    # ── 统一认证路由 ──
    auth_routes = _get_auth_routes()
    if self.path in auth_routes:
        method, handler = auth_routes[self.path]
        if method == "POST":
            handler(self)
            return

    # ... 原有的do_POST逻辑继续 ...
'''

# ── API中间件装饰器 (用于保护现有API端点) ──

def require_auth(handler_func):
    """
    认证装饰器 - 保护需要登录的API端点

    用法:
        @require_auth
        def handle_protected_api(self):
            # 只有认证用户才能到达这里
            auth = self.state.get('auth')
            username = auth.username
            ...
    """
    def wrapper(self, *args, **kwargs):
        adapter = get_auth_adapter()

        headers_dict = dict(self.headers.items())
        cookie_header = headers_dict.get("Cookie", "")
        cookies = {}
        if cookie_header:
            for item in cookie_header.split(';'):
                item = item.strip()
                if '=' in item:
                    k, v = item.split('=', 1)
                    cookies[k.strip()] = v.strip()

        context, error = adapter.authenticate_request(headers_dict, cookies, required=True)

        if error:
            self.send_error(error["status_code"], error["error"])
            return

        # 注入认证上下文
        if not hasattr(self, 'state'):
            self.state = {}
        self.state['auth'] = context

        return handler_func(self, *args, **kwargs)

    return wrapper


# ── 前端JavaScript辅助代码 ──

FRONTEND_AUTH_JS = '''
// ══════════════════════════════════════════════════
// 火瞳统一认证前端辅助 (P1-B)
// ══════════════════════════════════════════════════

const HotpotAuth = {
    // Token存储键名
    TOKEN_KEY: 'hotpot_access_token',
    LOGIN_MODE_KEY: 'hotpot_login_mode',

    // ── 登录方法 ──

    async jwtLogin(username, password) {
        const resp = await fetch('/api/v1/auth/jwt-login', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username, password})
        });
        const data = await resp.json();
        if (data.ok) {
            this.saveToken(data.access_token, data.login_mode);
        }
        return data;
    },

    async pinLogin(pin) {
        const resp = await fetch('/api/v1/auth/pin-login', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({pin})
        });
        const data = await resp.json();
        if (data.ok) {
            this.saveToken(data.access_token, data.login_mode);
        }
        return data;
    },

    // ── Token管理 ──

    saveToken(token, mode) {
        localStorage.setItem(this.TOKEN_KEY, token);
        localStorage.setItem(this.LOGIN_MODE_KEY, mode || 'jwt');
    },

    getToken() {
        return localStorage.getItem(this.TOKEN_KEY);
    },

    clearToken() {
        localStorage.removeItem(this.TOKEN_KEY);
        localStorage.removeItem(this.LOGIN_MODE_KEY);
    },

    isAuthenticated() {
        return !!this.getToken();
    },

    // ── API调用封装 ──

    async apiCall(url, options = {}) {
        const token = this.getToken();
        if (token) {
            options.headers = Object.assign({}, options.headers, {
                'Authorization': `Bearer ${token}`
            });
        }

        const resp = await fetch(url, options);

        // 自动处理401 (Token过期)
        if (resp.status === 401) {
            this.clearToken();
            window.location.href = '/login.html?redirect=' + encodeURIComponent(url);
            throw new Error('认证已过期，请重新登录');
        }

        return resp;
    },

    // ── 登出 ──

    async logout() {
        try {
            await fetch('/api/v1/auth/logout', {method: 'POST'});
        } catch (e) {}
        this.clearToken();
        window.location.href = '/login.html';
    },

    // ── Token刷新 ──

    async refreshToken() {
        const token = this.getToken();
        if (!token) throw new Error('无有效Token');
        const resp = await fetch('/api/v1/auth/refresh', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({refresh_token: token})
        });
        const data = await resp.json();
        if (data.ok) {
            this.saveToken(data.access_token, data.login_mode);
        }
        return data;
    },

    // ── 获取当前用户信息 ──

    async getStatus() {
        const resp = await fetch('/api/v1/auth/status');
        return await resp.json();
    }
};

// 导出到全局
window.HotpotAuth = HotpotAuth;
'''
