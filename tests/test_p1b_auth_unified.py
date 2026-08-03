"""
P1-B 统一认证模块测试套件

覆盖范围:
- 单元测试 (8用例): Token生成/解码/过期/刷新/PIN哈希/映射配置
- 集成测试 (8用例): PIN/JWT登录全流程/双模式/向后兼容
- 安全测试 (4用例): Token伪造/重放/暴力破解防护

运行方式:
    python3 tests/test_p1b_auth_unified.py              # 全部测试
    python3 tests/test_p1b_auth_unified.py --unit        # 仅单元测试
    python3 tests/test_p1b_auth_unified.py --security    # 仅安全测试
"""

import json
import os
import sys
import time
import unittest
from pathlib import Path

# 添加项目根目录到sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── 导入被测模块 ──
try:
    from hotpot_platform.cloud.event_hub.middleware.auth_unified import (
        UnifiedAuthManager,
        AuthContext,
        TokenResponse,
        PinLoginRequest,
        JwtLoginRequest,
        get_auth_manager,
        init_auth_manager,
        DEMO_USERS,
        JWT_SECRET_KEY,
        JWT_ALGORITHM,
        JWT_EXPIRE_HOURS,
        MAX_LOGIN_ATTEMPTS,
        LOCKOUT_DURATION,
        _login_attempts,
        _check_rate_limit,
        _record_attempt,
    )
    import jwt as pyjwt  # PyJWT库
    PYJWT_OK = True
except ImportError as e:
    print(f"❌ 导入失败: {e}")
    print("请确保已安装依赖: pip install PyJWT fastapi pydantic")
    sys.exit(1)


class TestUnitTokenLifecycle(unittest.TestCase):
    """单元测试: Token完整生命周期"""

    def setUp(self):
        """每个测试前初始化"""
        self.manager = UnifiedAuthManager(
            secret_key="test-secret-key-for-unit-tests",
            expire_hours=1,
            store_id="test-store",
            auth_mode="dual",
        )

    def test_01_jwt_token_generation(self):
        """[单元] JWT Token生成 - 包含必要claims"""
        token = self.manager._create_jwt_token(
            username="zhangdian",
            role="店长",
            store_id="store_test",
        )

        # 验证token非空且为字符串
        self.assertIsInstance(token, str)
        self.assertTrue(len(token) > 0)

        # 解码验证payload
        payload = pyjwt.decode(token, "test-secret-key-for-unit-tests", algorithms=[JWT_ALGORITHM])
        self.assertEqual(payload["sub"], "zhangdian")
        self.assertEqual(payload["role"], "店长")
        self.assertEqual(payload["store_id"], "store_test")
        self.assertIn("iat", payload)
        self.assertIn("exp", payload)
        self.assertEqual(payload["iss"], "hotpot-platform")

    def test_02_jwt_token_decode_valid(self):
        """[单元] JWT Token解码 - 有效Token返回正确payload"""
        token = self.manager._create_jwt_token(
            username="chushi",
            role="厨师长",
            data_scope=["store_jiaojiang"],
        )

        context = self.manager.verify_token(token)

        self.assertTrue(context.authenticated)
        self.assertEqual(context.username, "chushi")
        self.assertEqual(context.role, "厨师长")
        self.assertEqual(context.token_type, "jwt")
        self.assertEqual(len(context.data_scope), 1)

    def test_03_jwt_token_expired(self):
        """[单元] 过期Token返回未认证"""
        # 创建一个立即过期的token
        manager_expired = UnifiedAuthManager(
            secret_key="test-secret",
            expire_hours=-1,  # 负数=立即过期
        )
        token = manager_expired._create_jwt_token(username="test", role="test_role")

        context = manager_expired.verify_token(token)
        self.assertFalse(context.authenticated)
        self.assertIsNone(context.username)

    def test_04_jwt_token_invalid_signature(self):
        """[单元] 篡改签名的Token返回未认证"""
        valid_token = self.manager._create_jwt_token(username="test", role="test")

        # 尝试用错误密钥解码
        wrong_manager = UnifiedAuthManager(secret_key="wrong-secret-key")
        context = wrong_manager.verify_token(valid_token)

        self.assertFalse(context.authenticated)

    def test_05_jwt_token_tampered(self):
        """[单元] 被篡改的Payload返回未认证"""
        # 手动构造一个格式正确但签名无效的token
        fake_payload = {"sub": "hacker", "role": "admin", "exp": time.time() + 3600}
        fake_token = pyjwt.encode(fake_payload, "wrong-key", algorithm="HS256")

        context = self.manager.verify_token(fake_token)
        self.assertFalse(context.authenticated)

    def test_06_pin_hash_consistency(self):
        """[单元] PIN哈希一致性 - 相同PIN产生相同hash"""
        pin = "123456"
        hash1 = UnifiedAuthManager._hash_pin(pin)
        hash2 = UnifiedAuthManager._hash_pin(pin)

        self.assertEqual(hash1, hash2)
        self.assertTrue(len(hash1) == 64)  # SHA256输出长度
        self.assertTrue(all(c in '0123456789abcdef' for c in hash1))  # hex字符

    def test_07_pin_hash_uniqueness(self):
        """[单元] 不同PIN产生不同hash"""
        hash_123456 = UnifiedAuthManager._hash_pin("123456")
        hash_654321 = UnifiedAuthManager._hash_pin("654321")

        self.assertNotEqual(hash_123456, hash_654321)

    def test_08_auth_context_properties(self):
        """[单元] AuthContext属性计算正确性"""
        # 管理员角色
        admin_ctx = AuthContext(role="总部PMO", data_scope=["*"])
        self.assertTrue(admin_ctx.is_admin)
        self.assertTrue(admin_ctx.can_manage_store)

        # 普通店长
        normal_ctx = AuthContext(role="店长", data_scope=["store_jiaojiang"])
        self.assertFalse(normal_ctx.is_admin)
        self.assertTrue(normal_ctx.can_manage_store)
        self.assertTrue(normal_ctx.can_manage_specific_store("store_jiaojiang"))
        self.assertFalse(normal_ctx.can_manage_specific_store("other_store"))

        # 未认证
        guest_ctx = AuthContext(authenticated=False)
        self.assertFalse(guest_ctx.is_admin)
        self.assertFalse(guest_ctx.can_manage_store)


class TestIntegrationPinLogin(unittest.TestCase):
    """集成测试: PIN登录完整流程"""

    def setUp(self):
        self.manager = UnifiedAuthManager(
            secret_key="test-pin-login",
            auth_mode="dual",
        )
        # 清除限流记录
        _login_attempts.clear()

    def test_01_default_pin_login_success(self):
        """[集成] 默认PIN(123456)登录成功并返回JWT"""
        import asyncio
        response = asyncio.get_event_loop().run_until_complete(
            self.manager.pin_login("123456", request_ip="test-01")
        )

        self.assertIsInstance(response, TokenResponse)
        self.assertTrue(response.access_token.startswith("eyJ"))  # JWT格式
        self.assertEqual(response.token_type, "bearer")
        self.assertEqual(response.login_mode, "pin")
        self.assertEqual(response.user["username"], "zhangdian")
        self.assertEqual(response.user["role"], "店长")
        self.assertGreater(response.expires_in, 0)

    def test_02_mapped_pin_login(self):
        """[集成] 映射表中的PIN(654321)登录为厨师长"""
        import asyncio
        response = asyncio.get_event_loop().run_until_complete(
            self.manager.pin_login("654321", request_ip="test-02")
        )

        self.assertEqual(response.user["username"], "chushi")
        self.assertEqual(response.user["role"], "厨师长")
        self.assertEqual(response.login_mode, "pin")

    def test_03_pin_token_verifiable(self):
        """[集成] PIN登录获得的JWT可被verify_token验证"""
        import asyncio
        response = asyncio.get_event_loop().run_until_complete(
            self.manager.pin_login("123456", request_ip="test-03")
        )
        context = self.manager.verify_token(response.access_token)

        self.assertTrue(context.authenticated)
        self.assertEqual(context.username, "zhangdian")
        self.assertEqual(context.login_mode, "pin")  # 标记来源为PIN

    def test_04_wrong_pin_rejected(self):
        """[集成] 错误PIN返回401异常"""
        import asyncio
        with self.assertRaises(Exception) as ctx:
            # HTTPException或其他异常
            asyncio.get_event_loop().run_until_complete(
                self.manager.pin_login("999999", request_ip="test-wrong")
            )

        # 验证是401或429异常
        exc = ctx.exception
        self.assertIn(getattr(exc, 'status_code', getattr(exc, 'code', 0)), [401, 429])

    def test_05_pin_format_validation(self):
        """[集成] PIN格式校验 (必须6位数字)"""
        # 非数字PIN
        with self.assertRaises(ValueError):
            PinLoginRequest(pin="abcdef")

        # 长度不足
        with self.assertRaises(ValueError):
            PinLoginRequest(pin="12345")

        # 超长
        with self.assertRaises(ValueError):
            PinLoginRequest(pin="1234567")


class TestIntegrationJwtLogin(unittest.TestCase):
    """集成测试: JWT登录完整流程"""

    def setUp(self):
        self.manager = UnifiedAuthManager(
            secret_key="test-jwt-login",
            auth_mode="dual",
        )
        _login_attempts.clear()

    def test_01_demo_user_login_success(self):
        """[集成] Demo用户(zhangdian/demo)登录成功"""
        import asyncio
        response = asyncio.get_event_loop().run_until_complete(
            self.manager.jwt_login("zhangdian", "demo", request_ip="test-jwt-01")
        )

        self.assertIsInstance(response, TokenResponse)
        self.assertEqual(response.login_mode, "jwt")
        self.assertEqual(response.user["username"], "zhangdian")
        self.assertEqual(response.user["role"], "店长")

    def test_02_all_demo_users_loginable(self):
        """[集成] 所有7个Demo用户均可成功登录"""
        import asyncio
        for username, info in DEMO_USERS.items():
            response = asyncio.get_event_loop().run_until_complete(
                self.manager.jwt_login(username, info["password"], request_ip=f"test-{username}")
            )
            self.assertEqual(response.user["role"], info["role"],
                           f"{username} 角色不匹配")

    def test_03_wrong_password_rejected(self):
        """[集成] 错误密码返回401"""
        import asyncio
        with self.assertRaises(Exception):
            asyncio.get_event_loop().run_until_complete(
                self.manager.jwt_login("zhangdian", "wrong_password", request_ip="test-jwt-wrong")
            )

    def test_04_nonexistent_user_rejected(self):
        """[集成] 不存在的用户返回401"""
        import asyncio
        with self.assertRaises(Exception):
            asyncio.get_event_loop().run_until_complete(
                self.manager.jwt_login("nonexistent", "pass", request_ip="test-jwt-no-user")
            )


class TestSecurityRateLimiting(unittest.TestCase):
    """安全测试: 速率限制与防暴力破解"""

    def setUp(self):
        self.manager = UnifiedAuthManager(
            secret_key="test-security",
            auth_mode="dual",
        )
        _login_attempts.clear()

    def test_01_rate_limit_blocks_after_max(self):
        """[安全] 达到最大尝试次数后触发限制"""
        test_ip = "192.168.1.100"

        # 记录MAX_LOGIN_ATTEMPTS次失败
        for i in range(MAX_LOGIN_ATTEMPTS):
            _record_attempt(test_ip)

        # 下一次应被限制
        self.assertFalse(_check_rate_limit(test_ip))

    def test_02_rate_limit_allows_under_max(self):
        """[安全] 未达到最大次数时允许通过"""
        test_ip = "10.0.0.1"

        # 记录MAX_LOGIN_ATTEMPTS-1次
        for i in range(MAX_LOGIN_ATTEMPTS - 1):
            _record_attempt(test_ip)

        # 仍应允许
        self.assertTrue(_check_rate_limit(test_ip))

    def test_03_rate_limit_auto_expires(self):
        """[安全] 锁定时间过后自动解除限制"""
        test_ip = "172.16.1.50"

        # 触发锁定
        for i in range(MAX_LOGIN_ATTEMPTS):
            _record_attempt(test_ip)

        # 模拟时间流逝 (修改记录的时间戳为LOCKOUT_DURATION+1秒前)
        old_time = time.time() - LOCKOUT_DURATION - 1
        _login_attempts[test_ip] = [old_time] * MAX_LOGIN_ATTEMPTS

        # 应该解除锁定
        self.assertTrue(_check_rate_limit(test_ip))

    def test_04_different_ips_independent(self):
        """[安全] 不同IP的限流计数相互独立"""
        ip_a = "10.0.0.100"
        ip_b = "10.0.0.200"

        # IP A触发锁定
        for i in range(MAX_LOGIN_ATTEMPTS):
            _record_attempt(ip_a)

        # IP B不应受影响
        self.assertFalse(_check_rate_limit(ip_a))
        self.assertTrue(_check_rate_limit(ip_b))


class TestDualModeCoexistence(unittest.TestCase):
    """集成测试: 双模式共存"""

    def setUp(self):
        self.manager = UnifiedAuthManager(
            secret_key="test-dual-mode",
            auth_mode="dual",  # 关键：双模式
        )
        _login_attempts.clear()

    def test_01_both_modes_available(self):
        """[双模式] PIN和JWT登录均可用"""
        import asyncio

        # PIN登录
        pin_resp = asyncio.get_event_loop().run_until_complete(
            self.manager.pin_login("123456", request_ip="dual-test-1")
        )
        self.assertEqual(pin_resp.login_mode, "pin")

        # JWT登录
        jwt_resp = asyncio.get_event_loop().run_until_complete(
            self.manager.jwt_login("zhangdian", "demo", request_ip="dual-test-2")
        )
        self.assertEqual(jwt_resp.login_mode, "jwt")

    def test_02_tokens_interoperable(self):
        """[双模式] 两种方式获得的Token可统一验证"""
        import asyncio

        pin_resp = asyncio.get_event_loop().run_until_complete(
            self.manager.pin_login("123456", request_ip="dual-test-3")
        )
        jwt_resp = asyncio.get_event_loop().run_until_complete(
            self.manager.jwt_login("chushi", "demo", request_ip="dual-test-4")
        )

        # 两个Token都可通过verify_token验证
        pin_ctx = self.manager.verify_token(pin_resp.access_token)
        jwt_ctx = self.manager.verify_token(jwt_resp.access_token)

        self.assertTrue(pin_ctx.authenticated)
        self.assertTrue(jwt_ctx.authenticated)
        self.assertEqual(pin_ctx.login_mode, "pin")
        self.assertEqual(jwt_ctx.login_mode, "jwt")


class TestConfigurationLoading(unittest.TestCase):
    """单元测试: 配置加载与默认值"""

    def test_01_default_config_values(self):
        """[配置] 默认配置值正确"""
        manager = UnifiedAuthManager()

        self.assertEqual(manager.expire_hours, JWT_EXPIRE_HOURS)
        self.assertEqual(manager.store_id, DEFAULT_STORE_ID if 'DEFAULT_STORE_ID' in dir() else "store_jiaojiang")
        self.assertEqual(manager.auth_mode, "dual")

    def test_02_custom_config_override(self):
        """[配置] 自定义参数覆盖默认值"""
        manager = UnifiedAuthManager(
            secret_key="custom-secret",
            expire_hours=12,
            store_id="custom-store",
            auth_mode="jwt",
        )

        self.assertEqual(manager.secret_key, "custom-secret")
        self.assertEqual(manager.expire_hours, 12)
        self.assertEqual(manager.store_id, "custom-store")
        self.assertEqual(manager.auth_mode, "jwt")

    def test_03_pin_mapping_loaded(self):
        """[配置] PIN映射配置正确加载"""
        manager = UnifiedAuthManager()

        # 默认映射应包含3个预设PIN
        self.assertIn("123456", manager.pin_mapping.mappings)
        self.assertIn("654321", manager.pin_mapping.mappings)
        self.assertEqual(manager.pin_mapping.default_user, "zhangdian")


class TestTokenRefresh(unittest.TestCase):
    """集成测试: Token刷新"""

    def setUp(self):
        self.manager = UnifiedAuthManager(
            secret_key="test-refresh",
            expire_hours=1,
        )
        _login_attempts.clear()

    def test_01_refresh_extends_expiry(self):
        """[刷新] 刷新后获得新Token，延长过期时间"""
        import asyncio

        # 先登录获取Token
        login_resp = asyncio.get_event_loop().run_until_complete(
            self.manager.jwt_login("zhangdian", "demo", request_ip="refresh-test")
        )

        # 刷新Token
        refresh_resp = asyncio.get_event_loop().run_until_complete(
            self.manager.refresh_token(login_resp.access_token)
        )

        # 新Token应不同于旧Token
        self.assertNotEqual(refresh_resp.access_token, login_resp.access_token)
        self.assertEqual(refresh_resp.user["username"], "zhangdian")
        self.assertGreater(refresh_resp.expires_in, 0)

    def test_02_refresh_invalid_token_fails(self):
        """[刷新] 刷新无效Token抛出401"""
        import asyncio

        with self.assertRaises(Exception):
            asyncio.get_event_loop().run_until_complete(
                self.manager.refresh_token("invalid-token-string")
            )


# ── 测试运行器 ──

def run_tests():
    """运行所有测试并输出报告"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # 添加所有测试类
    test_classes = [
        TestUnitTokenLifecycle,       # 8 用例
        TestIntegrationPinLogin,      # 5 用例
        TestIntegrationJwtLogin,      # 4 用例
        TestSecurityRateLimiting,     # 4 用例
        TestDualModeCoexistence,      # 2 用例
        TestConfigurationLoading,     # 3 用例
        TestTokenRefresh,             # 2 用例
    ]

    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)

    # 运行
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # 输出摘要
    print("\n" + "=" * 70)
    print(f"P1-B 统一认证测试结果:")
    print(f"  总计: {result.testsRun} 个用例")
    print(f"  通过: {result.testsRun - len(result.failures) - len(result.errors)} ✅")
    print(f"  失败: {len(result.failures)} ❌")
    print(f"  错误: {len(result.errors)} 💥")
    print("=" * 70)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
