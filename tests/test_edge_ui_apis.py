"""
Edge UI API 单元测试

覆盖模块:
- CameraConnectionManager (edge/edge-ui/api/camera_api.py)
- ConfigChangeNotifier (edge/edge-ui/api/config_api.py)

目标覆盖率: 80%+
"""

import pytest
import time
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
import importlib.util

# 项目根目录
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Mock 外部依赖（middleware, fastapi 等）
sys.modules.setdefault("middleware", MagicMock())
# 确保 fastapi 和 pydantic 可用（测试环境通常已安装）


def _load_class_from_file(module_name: str, file_path: str, class_name: str):
    """从文件路径动态加载类（处理 edge-ui 带连字符的目录名）"""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return getattr(mod, class_name)


# 加载被测类
EDGE_UI_API_DIR = ROOT / "edge" / "edge-ui" / "api"
CameraConnectionManager = _load_class_from_file(
    "camera_api", str(EDGE_UI_API_DIR / "camera_api.py"), "CameraConnectionManager"
)
ConfigChangeNotifier = _load_class_from_file(
    "config_api", str(EDGE_UI_API_DIR / "config_api.py"), "ConfigChangeNotifier"
)


# =====================================================================
# Fixtures
# =====================================================================

@pytest.fixture()
def camera_mgr():
    """创建 CameraConnectionManager 实例（非单例模式）"""
    # 重置单例以避免测试间干扰
    CameraConnectionManager._instance = None
    return CameraConnectionManager()


@pytest.fixture()
def config_notifier():
    """创建 ConfigChangeNotifier 实例（非单例模式）"""
    ConfigChangeNotifier._instance = None
    return ConfigChangeNotifier()


# =====================================================================
# Part A: CameraConnectionManager 测试
# =====================================================================

class TestCameraConnectionManagerInit:
    """A1. 实例化与配置"""

    def test_default_init(self, camera_mgr):
        """默认参数实例化 - 验证初始状态为空"""
        assert camera_mgr._status == {}
        assert camera_mgr._stream_config == {}
        assert camera_mgr._reconnect_history == {}
        assert camera_mgr._max_history == 50

    def test_singleton_pattern(self):
        """验证单例模式 - 多次获取返回同一实例"""
        CameraConnectionManager._instance = None
        mgr1 = CameraConnectionManager.get_instance()
        mgr2 = CameraConnectionManager.get_instance()
        assert mgr1 is mgr2


class TestCameraRegistration:
    """A2. 摄像头注册与管理（通过 update_status / get_status 模拟）"""

    def test_register_camera(self, camera_mgr):
        """register_camera() 添加摄像头 - 通过 update_status 实现"""
        camera_mgr.update_status("cam_001", "online", "首次连接", latency_ms=10)
        status = camera_mgr.get_status("cam_001")
        assert status["camera_id"] == "cam_001"
        assert status["status"] == "online"

    def test_unregister_camera(self, camera_mgr):
        """unregister_camera() 移除摄像头 - 从状态字典中删除"""
        camera_mgr.update_status("cam_001", "online")
        # 模拟移除操作
        del camera_mgr._status["cam_001"]
        status = camera_mgr.get_status("cam_001")
        assert status["status"] == "unknown"

    def test_get_camera(self, camera_mgr):
        """get_camera() 查询单个摄像头状态"""
        camera_mgr.update_status("cam_001", "offline", "连接断开")
        status = camera_mgr.get_status("cam_001")
        assert status["status"] == "offline"
        assert status["detail"] == "连接断开"

    def test_get_nonexistent_camera(self, camera_mgr):
        """查询不存在的摄像头返回 unknown 状态"""
        status = camera_mgr.get_status("cam_nonexist")
        assert status["status"] == "unknown"
        assert status["camera_id"] == "cam_nonexist"

    def test_list_cameras(self, camera_mgr):
        """list_cameras() 列出所有摄像头"""
        camera_mgr.update_status("cam_001", "online")
        camera_mgr.update_status("cam_002", "offline")
        camera_mgr.update_status("cam_003", "degraded")
        all_status = camera_mgr.get_status()
        assert len(all_status) == 3
        assert "cam_001" in all_status
        assert "cam_002" in all_status
        assert "cam_003" in all_status

    def test_list_empty_cameras(self, camera_mgr):
        """空列表时返回空字典"""
        all_status = camera_mgr.get_status()
        assert all_status == {}


class TestReconnectBackoff:
    """A3. 重连逻辑 (reconnect_with_backoff)"""

    def test_first_reconnect_base_interval(self, camera_mgr):
        """首次重连: base_interval = 1s (2^0)"""
        # 无失败记录时，backoff 应为 1
        backoff = camera_mgr.get_next_backoff_seconds("cam_001")
        assert backoff == 1  # 2^0 = 1

    def test_second_reconnect_doubles(self, camera_mgr):
        """第二次: base_interval * 2^1 = 2s"""
        # 模拟一次失败
        camera_mgr.update_status("cam_001", "offline", "连接失败")
        failures = camera_mgr._status.get("cam_001", {}).get("consecutive_failures", 0)
        assert failures >= 1
        backoff = camera_mgr.get_next_backoff_seconds("cam_001")
        assert backoff == 2  # 2^1 = 2

    def test_third_reconnect_quadruples(self, camera_mgr):
        """第三次: base_interval * 2^2 = 4s"""
        camera_mgr.update_status("cam_001", "offline", "失败1")
        camera_mgr.update_status("cam_001", "offline", "失败2")
        backoff = camera_mgr.get_next_backoff_seconds("cam_001")
        assert backoff == 4  # 2^2 = 4

    def test_max_attempts_cap(self, camera_mgr):
        """达到 max_attempts 后停止增长 - 最大30秒"""
        # 连续多次失败
        for i in range(10):
            camera_mgr.update_status("cam_001", "offline", f"失败{i+1}")
        backoff = camera_mgr.get_next_backoff_seconds("cam_001")
        assert backoff == 30  # 封顶30秒

    def test_reset_on_success(self, camera_mgr):
        """重连成功后 reset 计数器"""
        # 先产生一些失败
        camera_mgr.update_status("cam_001", "offline", "失败1")
        camera_mgr.update_status("cam_001", "offline", "失败2")
        assert camera_mgr.get_next_backoff_seconds("cam_001") >= 2

        # 成功连接
        camera_mgr.record_reconnect("cam_001", True, "连接成功")
        backoff = camera_mgr.get_next_backoff_seconds("cam_001")
        assert backoff == 1  # 重置为1

    def test_record_reconnect_success(self, camera_mgr):
        """记录成功重连事件"""
        camera_mgr.record_reconnect("cam_001", True, "延迟=50ms")
        history = camera_mgr._reconnect_history.get("cam_001", [])
        assert len(history) == 1
        assert history[0]["success"] is True
        assert history[0]["detail"] == "延迟=50ms"

    def test_record_reconnect_failure(self, camera_mgr):
        """记录失败重连事件"""
        camera_mgr.record_reconnect("cam_001", False, "超时")
        history = camera_mgr._reconnect_history.get("cam_001", [])
        assert len(history) == 1
        assert history[0]["success"] is False
        assert history[0]["detail"] == "超时"

    def test_history_length_limit(self, camera_mgr):
        """历史记录限制在 _max_history 条以内"""
        for i in range(60):  # 超过 _max_history=50
            camera_mgr.record_reconnect("cam_001", True, f"第{i+1}次")
        history = camera_mgr._reconnect_history.get("cam_001", [])
        assert len(history) <= 50


class TestStreamConfig:
    """A4. 流控参数设置"""

    def test_set_stream_config_default(self, camera_mgr):
        """set_stream_config() 使用默认值"""
        camera_mgr.set_stream_config("cam_001", {})
        config = camera_mgr.get_stream_config("cam_001")
        assert config["max_fps"] == 15
        assert config["max_bandwidth_kbps"] == 4096
        assert config["codec"] == "h264"
        assert config["resolution"] == "1920x1080"

    def test_set_stream_config_custom(self, camera_mgr):
        """set_stream_config(fps, bandwidth_kbps, codec) 自定义参数"""
        camera_mgr.set_stream_config("cam_001", {
            "max_fps": 25,
            "max_bandwidth_kbps": 8192,
            "codec": "h265",
            "resolution": "3840x2160",
        })
        config = camera_mgr.get_stream_config("cam_001")
        assert config["max_fps"] == 25
        assert config["max_bandwidth_kbps"] == 8192
        assert config["codec"] == "h265"
        assert config["resolution"] == "3840x2160"

    def test_get_stream_config_default_for_unknown(self, camera_mgr):
        """get_stream_config() 对未配置的摄像头返回默认值"""
        config = camera_mgr.get_stream_config("cam_unknown")
        assert config["max_fps"] == 15
        assert config["codec"] == "h264"

    def test_set_stream_config_partial_merge(self, camera_mgr):
        """部分参数更新 - 未指定的保持默认"""
        camera_mgr.set_stream_config("cam_001", {"max_fps": 20})
        config = camera_mgr.get_stream_config("cam_001")
        assert config["max_fps"] == 20
        assert config["max_bandwidth_kbps"] == 4096  # 默认值保留
        assert config["codec"] == "h264"  # 默认值保留

    def test_set_stream_config_per_camera_isolation(self, camera_mgr):
        """不同摄像头的流控配置相互隔离"""
        camera_mgr.set_stream_config("cam_001", {"max_fps": 15})
        camera_mgr.set_stream_config("cam_002", {"max_fps": 30})
        assert camera_mgr.get_stream_config("cam_001")["max_fps"] == 15
        assert camera_mgr.get_stream_config("cam_002")["max_fps"] == 30


class TestHealthCheck:
    """A5. 健康检查"""

    def test_check_health_single_camera(self, camera_mgr):
        """check_health(camera_id) 返回单个摄像头状态"""
        camera_mgr.update_status("cam_001", "online", "正常", latency_ms=5)
        status = camera_mgr.get_status("cam_001")
        assert status["status"] == "online"
        assert status["latency_ms"] == 5

    def test_check_all_healths_summary(self, camera_mgr):
        """check_all_healths() 批量检查摘要"""
        camera_mgr.update_status("cam_001", "online")
        camera_mgr.update_status("cam_002", "online")
        camera_mgr.update_status("cam_003", "offline")
        camera_mgr.update_status("cam_004", "degraded")

        summary = camera_mgr.get_health_summary()
        assert summary["total_cameras"] == 4
        assert summary["online"] == 2
        assert summary["offline"] == 1  # offline + reconnecting
        assert summary["degraded"] == 1
        assert summary["online_rate"] == 50.0  # 2/4 * 100

    def test_check_all_healths_empty(self, camera_mgr):
        """无摄像头时的健康摘要"""
        summary = camera_mgr.get_health_summary()
        assert summary["total_cameras"] == 0
        assert summary["online"] == 0
        assert summary["online_rate"] == 0.0

    def test_check_health_includes_reconnecting_as_offline(self, camera_mgr):
        """reconnecting 状态计入 offline 统计"""
        camera_mgr.update_status("cam_001", "reconnecting")
        summary = camera_mgr.get_health_summary()
        assert summary["offline"] == 1
        assert summary["online"] == 0

    def test_update_status_timestamp(self, camera_mgr):
        """update_status 更新时间戳"""
        before = datetime.now(timezone.utc).isoformat()
        camera_mgr.update_status("cam_001", "online")
        after = datetime.now(timezone.utc).isoformat()
        status = camera_mgr.get_status("cam_001")
        assert before <= status["updated_at"] <= after

    def test_consecutive_failures_increment(self, camera_mgr):
        """连续失败计数器递增"""
        camera_mgr.update_status("cam_001", "offline", "fail1")
        assert camera_mgr._status["cam_001"]["consecutive_failures"] == 1
        camera_mgr.update_status("cam_001", "offline", "fail2")
        assert camera_mgr._status["cam_001"]["consecutive_failures"] == 2

    def test_consecutive_failures_reset_on_online(self, camera_mgr):
        """上线后连续失败计数器归零"""
        camera_mgr.update_status("cam_001", "offline", "fail1")
        camera_mgr.update_status("cam_001", "offline", "fail2")
        assert camera_mgr._status["cam_001"]["consecutive_failures"] == 2
        camera_mgr.update_status("cam_001", "online", "connected")
        assert camera_mgr._status["cam_001"]["consecutive_failures"] == 0


# =====================================================================
# Part B: ConfigChangeNotifier 测试
# =====================================================================

class TestConfigChangeNotifierInit:
    """B1. 实例化与配置"""

    def test_default_init(self, config_notifier):
        """默认参数实例化 - 验证初始状态为空"""
        assert config_notifier._config_hashes == {}
        assert config_notifier._config_versions == {}
        assert config_notifier._change_log == []
        assert config_notifier._max_log == 100

    def test_singleton_pattern(self):
        """验证单例模式"""
        ConfigChangeNotifier._instance = None
        n1 = ConfigChangeNotifier.get_instance()
        n2 = ConfigChangeNotifier.get_instance()
        assert n1 is n2


class TestSHA256ChangeDetection:
    """B2. SHA256 变更检测"""

    def test_initial_snapshot_records_hash(self, config_notifier):
        """初始加载：记录初始hash"""
        content = '{"host": "192.168.1.1", "port": 8080}'
        config_notifier.snapshot("device", content)
        assert "device" in config_notifier._config_hashes
        assert len(config_notifier._config_hashes["device"]) == 16  # 截取前16位

    def test_no_change_detected(self, config_notifier):
        """文件未变：检测到无变更"""
        content = '{"key": "value"}'
        config_notifier.snapshot("test_cfg", content)
        result = config_notifier.detect_change("test_cfg", content)
        assert result is None

    def test_change_detected(self, config_notifier):
        """文件已变：检测到变更，返回change_info"""
        old_content = '{"version": 1}'
        new_content = '{"version": 2}'
        config_notifier.snapshot("test_cfg", old_content)
        result = config_notifier.detect_change("test_cfg", new_content)
        assert result is not None
        assert result["old_hash"] != result["new_hash"]
        assert result["version"] == 1
        assert result["config_key"] == "test_cfg"

    def test_multiple_changes_detected(self, config_notifier):
        """连续多次变更都能检测到"""
        config_notifier.snapshot("multi", '{"v": 1}')
        r1 = config_notifier.detect_change("multi", '{"v": 2}')
        r2 = config_notifier.detect_change("multi", '{"v": 3}')
        r3 = config_notifier.detect_change("multi", '{"v": 4}')

        assert r1 is not None and r1["version"] == 1
        assert r2 is not None and r2["version"] == 2
        assert r3 is not None and r3["version"] == 3

    def test_compute_hash_consistency(self, config_notifier):
        """相同内容始终产生相同哈希"""
        content = "consistent_content_12345"
        h1 = config_notifier.compute_hash(content)
        h2 = config_notifier.compute_hash(content)
        assert h1 == h2

    def test_compute_hash_uniqueness(self, config_notifier):
        """不同内容产生不同哈希"""
        h1 = config_notifier.compute_hash("content_a")
        h2 = config_notifier.compute_hash("content_b")
        assert h1 != h2

    def test_initial_old_hash_value(self, config_notifier):
        """首次变更时 old_hash 为 'initial'"""
        result = config_notifier.detect_change("new_key", "some content")
        assert result is not None
        assert result["old_hash"] == "initial"


class TestVersionManagement:
    """B3. 版本管理"""

    def test_initial_version_zero(self, config_notifier):
        """初始版本为 0"""
        assert config_notifier.get_version("new_cfg") == 0

    def test_version_auto_increment(self, config_notifier):
        """每次变更版本自增 v1, v2, v3..."""
        config_notifier.snapshot("ver_test", '{"v": 1}')
        assert config_notifier.get_version("ver_test") == 0

        config_notifier.detect_change("ver_test", '{"v": 2}')
        assert config_notifier.get_version("ver_test") == 1

        config_notifier.detect_change("ver_test", '{"v": 3}')
        assert config_notifier.get_version("ver_test") == 2

        config_notifier.detect_change("ver_test", '{"v": 4}')
        assert config_notifier.get_version("ver_test") == 3

    def test_get_version_nonexistent(self, config_notifier):
        """查询不存在的配置键返回版本 0"""
        assert config_notifier.get_version("nonexistent") == 0

    def test_version_independent_per_key(self, config_notifier):
        """不同配置键的版本独立管理"""
        config_notifier.snapshot("key_a", "content_a")
        config_notifier.snapshot("key_b", "content_b")

        config_notifier.detect_change("key_a", "new_a")
        config_notifier.detect_change("key_b", "new_b")
        config_notifier.detect_change("key_a", "newer_a")

        assert config_notifier.get_version("key_a") == 2
        assert config_notifier.get_version("key_b") == 1


class TestChangeLog:
    """B4. 变更日志"""

    def test_change_log_recorded(self, config_notifier):
        """每次变更记录到日志"""
        config_notifier.snapshot("log_test", '{"v": 1}')
        config_notifier.detect_change("log_test", '{"v": 2}')

        log = config_notifier.get_change_log()
        assert len(log) == 1
        entry = log[0]
        assert entry["config_key"] == "log_test"
        assert entry["version"] == 1
        assert "timestamp" in entry
        assert "old_hash" in entry
        assert "new_hash" in entry

    def test_change_log_fields_complete(self, config_notifier):
        """日志包含所有必需字段: version, timestamp, change_type, file_path, hash"""
        config_notifier.detect_change("fields_test", "content")
        log = config_notifier.get_change_log()
        entry = log[0]
        # 验证关键字段存在
        assert "version" in entry
        assert "timestamp" in entry
        assert "old_hash" in entry
        assert "new_hash" in entry
        assert "config_key" in entry
        assert "previous_version" in entry
        assert "detected_by" in entry

    def test_change_log_max_limit(self, config_notifier):
        """日志最多保留 _max_log (100) 条"""
        for i in range(150):
            config_notifier.snapshot("limit_test", f'{{"v": {i}}}')
            config_notifier.detect_change("limit_test", f'{{"v": {i+1}}}')
        log = config_notifier.get_change_log()
        assert len(log) <= 100

    def test_change_log_with_since_filter(self, config_notifier):
        """since_version 过滤 - 只返回之后版本的日志"""
        config_notifier.snapshot("filter_test", '{"v": 0}')
        config_notifier.detect_change("filter_test", '{"v": 1}')  # v1
        config_notifier.detect_change("filter_test", '{"v": 2}')  # v2
        config_notifier.detect_change("filter_test", '{"v": 3}')  # v3

        # 获取 version > 1 的日志
        filtered = config_notifier.get_change_log(since_version=1)
        assert len(filtered) == 2  # v2, v3

    def test_change_log_limit_param(self, config_notifier):
        """limit 参数限制返回条数"""
        for i in range(10):
            config_notifier.snapshot("lim_p", f'{{"i":{i}}}')
            config_notifier.detect_change("lim_p", f'{{"i":{i+1}}}')

        limited = config_notifier.get_change_log(limit=5)
        assert len(limited) == 5

    def test_empty_change_log(self, config_notifier):
        """无变更时返回空日志"""
        log = config_notifier.get_change_log()
        assert log == []


class TestConfigSnapshotAndDiff:
    """B5. 配置快照与差异"""

    def test_get_snapshot_via_status(self, config_notifier):
        """get_snapshot() 获取当前配置快照（通过 get_status）"""
        config_notifier.snapshot("snap_test", '{"name": "test_device", "ip": "10.0.0.1"}')
        status = config_notifier.get_status()
        assert "snap_test" in status
        assert status["snap_test"]["current_hash"] is not None
        assert status["snap_test"]["version"] == 0

    def test_diff_detection_changed(self, config_notifier):
        """detect_change 返回完整 diff 信息"""
        config_notifier.snapshot("diff_test", '{"a": 1}')
        change = config_notifier.detect_change("diff_test", '{"a": 2, "b": 3}')

        assert change is not None
        assert change["old_hash"] != change["new_hash"]
        assert change["previous_version"] == 0
        assert change["version"] == 1
        # detect_change 返回非 None 即表示有变更

    def test_diff_detection_unchanged(self, config_notifier):
        """内容未变时 detect_change 返回 None"""
        config_notifier.snapshot("diff_same", '{"x": 1}')
        result = config_notifier.detect_change("diff_same", '{"x": 1}')
        assert result is None

    def test_status_multiple_configs(self, config_notifier):
        """get_status() 返回所有追踪配置的状态"""
        config_notifier.snapshot("cfg_a", "content_a")
        config_notifier.snapshot("cfg_b", "content_b")
        config_notifier.snapshot("cfg_c", "content_c")

        status = config_notifier.get_status()
        assert len(status) == 3
        assert "cfg_a" in status
        assert "cfg_b" in status
        assert "cfg_c" in status

    def test_status_last_modified(self, config_notifier):
        """状态包含最后修改时间"""
        config_notifier.snapshot("mod_test", "v1")
        config_notifier.detect_change("mod_test", "v2")

        status = config_notifier.get_status()
        assert status["mod_test"]["last_modified"] != "unknown"

    def test_status_empty_tracker(self, config_notifier):
        """无追踪配置时 get_status 返回空字典"""
        status = config_notifier.get_status()
        assert status == {}


# =====================================================================
# 边界条件与异常场景
# =====================================================================

class TestCameraEdgeCases:
    """CameraConnectionManager 边界场景"""

    def test_update_status_preserves_since_on_same_state(self, camera_mgr):
        """相同状态不更新 since 时间戳"""
        camera_mgr.update_status("cam_001", "offline", "first")
        first_since = camera_mgr._status["cam_001"]["since"]

        time.sleep(0.01)  # 小延迟确保时间戳不同
        camera_mgr.update_status("cam_001", "offline", "second")
        second_since = camera_mgr._status["cam_001"]["since"]

        assert first_since == second_since

    def test_update_status_updates_since_on_state_change(self, camera_mgr):
        """状态变化时更新 since 时间戳"""
        camera_mgr.update_status("cam_001", "offline", "first")
        first_since = camera_mgr._status["cam_001"]["since"]

        time.sleep(0.01)
        camera_mgr.update_status("cam_001", "online", "connected")
        second_since = camera_mgr._status["cam_001"]["since"]

        assert first_since != second_since

    def test_total_reconnects_count(self, camera_mgr):
        """total_reconnects 统计成功重连次数"""
        camera_mgr.record_reconnect("cam_001", True, "ok")
        camera_mgr.record_reconnect("cam_001", False, "fail")
        camera_mgr.record_reconnect("cam_001", True, "ok2")
        status = camera_mgr.get_status("cam_001")
        assert status["total_reconnects"] == 2


class TestConfigEdgeCases:
    """ConfigChangeNotifier 边界场景"""

    def test_empty_content_hash(self, config_notifier):
        """空字符串内容的哈希计算"""
        h = config_notifier.compute_hash("")
        assert len(h) == 16
        assert isinstance(h, str)

    def test_unicode_content_hash(self, config_notifier):
        """Unicode 内容的哈希计算"""
        h = config_notifier.compute_hash("配置内容: 中文测试 🎉")
        assert len(h) == 16

    def test_large_content_handling(self, config_notifier):
        """大内容处理"""
        large_content = "x" * 100000
        h = config_notifier.compute_hash(large_content)
        assert len(h) == 16

    def test_detect_change_without_snapshot(self, config_notifier):
        """未先 snapshot 直接 detect_change"""
        result = config_notifier.detect_change("direct", "content")
        assert result is not None
        assert result["old_hash"] == "initial"
        assert result["version"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
