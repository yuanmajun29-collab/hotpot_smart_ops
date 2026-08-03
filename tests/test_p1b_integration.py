"""
P1-B 集成测试套件 (Edge UI + Event Hub + 适配器)

覆盖范围:
- AuthAdapter 同步接口 (http.server兼容)
- Edge UI 路由注册与分发
- Event Hub FastAPI路由注册
- 前端JS辅助代码验证

运行方式:
    python3 tests/test_p1b_integration.py
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# 添加项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from hotpot_platform.cloud.event_hub.middleware.auth_adapter import (
        AuthAdapter,
        get_auth_adapter,
        init_auth_adapter,
        create_edge_ui_auth_handler,
        send_json_response,
    )
    from hotpot_platform.cloud.event_hub.middleware.auth_unified import (
        UnifiedAuthManager,
        AuthContext,
        TokenResponse,
        DEMO_USERS,
    )
except ImportError as e:
    print(f"❌ 导入失败: {e}")
    sys.exit(1)


class TestAuthAdapterSyncInterface(unittest.TestCase):
    """集成测试: AuthAdapter同步接口"""

    def setUp(self):
        self.adapter = AuthAdapter(
            secret_key="test-adapter-secret",
            auth_mode="dual",
        )

    def test_01_jwt_login_sync_success(self):
        """[适配器] JWT同步登录成功"""
        result = self.adapter.jwt_login_sync("zhangdian", "demo", client_ip="adapter-test")

        self.assertTrue(result["ok"])
        self.assertIn("access_token", result)
        self.assertEqual(result["login_mode"], "jwt")
        self.assertEqual(result["user"]["username"], "zhangdian")
        self.assertEqual(result["user"]["role"], "店长")

    def test_02_jwt_login_sync_wrong_password(self):
        """[适配器] JWT同步登录 - 错误密码"""
        result = self.adapter.jwt_login_sync("zhangdian", "wrong", client_ip="adapter-test")

        self.assertFalse(result["ok"])
        self.assertIn("error", result)
        self.assertEqual(result["status_code"], 401)

    def test_03_pin_login_sync_success(self):
        """[适配器] PIN同步登录成功"""
        result = self.adapter.pin_login_sync("123456", client_ip="adapter-test")

        self.assertTrue(result["ok"])
        self.assertEqual(result["login_mode"], "pin")
        self.assertEqual(result["user"]["username"], "zhangdian")

    def test_04_pin_login_sync_wrong_pin(self):
        """[适配器] PIN同步登录 - 错误PIN"""
        result = self.adapter.pin_login_sync("999999", client_ip="adapter-test")

        self.assertFalse(result["ok"])
        self.assertEqual(result["status_code"], 401)

    def test_05_verify_token_sync_valid(self):
        """[适配器] Token验证 - 有效Token"""
        login_result = self.adapter.jwt_login_sync("zhangdian", "demo")
        context = self.adapter.verify_token_sync(login_result["access_token"])

        self.assertTrue(context.authenticated)
        self.assertEqual(context.username, "zhangdian")

    def test_06_verify_token_sync_invalid(self):
        """[适配器] Token验证 - 无效Token"""
        context = self.adapter.verify_token_sync("invalid-token-string")

        self.assertFalse(context.authenticated)

    def test_07_refresh_token_sync(self):
        """[适配器] Token刷新成功"""
        login_result = self.adapter.jwt_login_sync("chushi", "demo")
        refresh_result = self.adapter.refresh_token_sync(login_result["access_token"])

        self.assertTrue(refresh_result["ok"])
        self.assertNotEqual(refresh_result["access_token"], login_result["access_token"])
        self.assertEqual(refresh_result["user"]["username"], "chushi")


class TestEdgeUIRouteRegistration(unittest.TestCase):
    """集成测试: Edge UI路由注册"""

    def test_01_routes_created(self):
        """[Edge UI] 认证路由正确生成"""
        routes = create_edge_ui_auth_handler()

        # 应包含5个端点
        expected_paths = [
            "/api/v1/auth/jwt-login",
            "/api/v1/auth/pin-login",
            "/api/v1/auth/refresh",
            "/api/v1/auth/logout",
            "/api/v1/auth/status",
        ]

        for path in expected_paths:
            self.assertIn(path, routes, f"缺少路由: {path}")
            method, handler = routes[path]
            self.assertIsNotNone(handler, f"{path} 缺少handler")

    def test_02_route_methods_correct(self):
        """[Edge UI] 路由HTTP方法正确"""
        routes = create_edge_ui_auth_handler()

        post_routes = ["/api/v1/auth/jwt-login", "/api/v1/auth/pin-login",
                      "/api/v1/auth/refresh", "/api/v1/auth/logout"]
        get_routes = ["/api/v1/auth/status"]

        for path in post_routes:
            method, _ = routes[path]
            self.assertEqual(method, "POST", f"{path} 应为POST")

        for path in get_routes:
            method, _ = routes[path]
            self.assertEqual(method, "GET", f"{path} 应为GET")


class TestAuthenticateRequest(unittest.TestCase):
    """集成测试: HTTP请求认证验证"""

    def setUp(self):
        self.adapter = AuthAdapter(secret_key="test-request-auth")

    def test_01_authenticated_request(self):
        """[请求认证] 已认证请求通过"""
        # 先获取有效token
        login_result = self.adapter.jwt_login_sync("zhangdian", "demo")
        token = login_result["access_token"]

        headers = {"Authorization": f"Bearer {token}"}
        context, error = self.adapter.authenticate_request(headers, required=True)

        self.assertIsNone(error)
        self.assertTrue(context.authenticated)
        self.assertEqual(context.username, "zhangdian")

    def test_02_unauthenticated_request_required(self):
        """[请求认证] 未认证请求返回错误(必须认证)"""
        headers = {}
        context, error = self.adapter.authenticate_request(headers, required=True)

        self.assertIsNotNone(error)
        self.assertFalse(context.authenticated)
        self.assertEqual(error["status_code"], 401)

    def test_03_unauthenticated_request_optional(self):
        """[请求认证] 未认证请求允许通过(可选认证)"""
        headers = {}
        context, error = self.adapter.authenticate_request(headers, required=False)

        self.assertIsNone(error)
        self.assertFalse(context.authenticated)

    def test_04_cookie_based_auth(self):
        """[请求认证] Cookie方式认证"""
        login_result = self.adapter.jwt_login_sync("zhangdian", "demo")
        token = login_result["access_token"]

        cookies = {"session_token": token}
        context, error = self.adapter.authenticate_request(
            headers={},
            cookies=cookies,
            required=True,
        )

        self.assertIsNone(error)
        self.assertTrue(context.authenticated)


class TestFrontendJsHelper(unittest.TestCase):
    """单元测试: 前端JS辅助代码验证"""

    def test_01_js_code_contains_key_functions(self):
        """[前端JS] 包含关键函数定义"""
        from hotpot_platform.cloud.event_hub.middleware.edge_ui_auth_integration import FRONTEND_AUTH_JS

        required_functions = [
            'jwtLogin',
            'pinLogin',
            'saveToken',
            'getToken',
            'clearToken',
            'isAuthenticated',
            'apiCall',
            'logout',
            'getStatus',
        ]

        for func_name in required_functions:
            self.assertIn(func_name, FRONTEND_AUTH_JS,
                          f"前端JS缺少函数: {func_name}")

    def test_02_js_code_contains_api_endpoints(self):
        """[前端JS] 包含正确的API端点"""
        from hotpot_platform.cloud.event_hub.middleware.edge_ui_auth_integration import FRONTEND_AUTH_JS

        endpoints = [
            '/api/v1/auth/jwt-login',
            '/api/v1/auth/pin-login',
            '/api/v1/auth/refresh',
            '/api/v1/auth/logout',
            '/api/v1/auth/status',
        ]

        for endpoint in endpoints:
            self.assertIn(endpoint, FRONTEND_AUTH_JS,
                          f"前端JS缺少端点: {endpoint}")


class TestGlobalSingleton(unittest.TestCase):
    """单元测试: 全局单例管理"""

    def test_01_get_auth_adapter_returns_instance(self):
        """[单例] get_auth_adapter() 返回实例"""
        adapter = get_auth_adapter()
        self.assertIsInstance(adapter, AuthAdapter)

    def test_02_get_auth_adapter_same_instance(self):
        """[单例] 多次调用返回同一实例"""
        a1 = get_auth_adapter()
        a2 = get_auth_adapter()
        self.assertIs(a1, a2)

    def test_03_init_auth_adapter_replaces(self):
        """[单例] init_auth_adapter() 替换实例"""
        adapter1 = get_auth_adapter()
        adapter2 = init_auth_adapter(secret_key="new-secret-for-test")
        adapter3 = get_auth_adapter()

        self.assertIsNot(adapter1, adapter2)
        self.assertIs(adapter2, adapter3)


# ── 测试运行器 ──

def run_tests():
    """运行集成测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_classes = [
        TestAuthAdapterSyncInterface,
        TestEdgeUIRouteRegistration,
        TestAuthenticateRequest,
        TestFrontendJsHelper,
        TestGlobalSingleton,
    ]

    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 70)
    print(f"P1-B 集成测试结果:")
    print(f"  总计: {result.testsRun} 个用例")
    print(f"  通过: {result.testsRun - len(result.failures) - len(result.errors)} ✅")
    print(f"  失败: {len(result.failures)} ❌")
    print(f"  错误: {len(result.errors)} 💥")
    print("=" * 70)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
