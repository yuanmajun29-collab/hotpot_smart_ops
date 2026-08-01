#!/usr/bin/env python3
"""
火瞳边缘盒子 · 统一配置管理器
对齐: WebUI架构设计v1.0 + 详细架构v1.1

职责:
- 加载/保存 edge_config.yml
- 南北向配置 CRUD（内存→持久化）
- 敏感字段自动脱敏
- 配置变更事件通知
- 运行时状态更新（心跳/摄像头等）
"""

import copy
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# ── 默认配置路径 ──
DEFAULT_CONFIG_DIR = Path(__file__).parent / "conf"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "edge_config.yml"

# ── 敏感字段列表（自动脱敏）──
SENSITIVE_FIELDS = {
    "password", "pwd", "secret", "token", "api_key", "apikey",
    "access_key", "private_key", "auth_token",
}


class ConfigManager:
    """统一配置管理中心（线程安全单例）"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, config_path: Optional[str] = None):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, config_path: Optional[str] = None):
        if self._initialized:
            return
        self._initialized = True

        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_FILE
        self._data: Dict[str, Any] = {}
        self._rw_lock = threading.RLock()
        self._listeners: List[Callable[[str, Any, Any], None]] = []
        self._last_load_time: float = 0
        self._load()

    # ══════════════════════════════════════
    # 加载/保存
    # ══════════════════════════════════════

    def _load(self) -> bool:
        """从YAML文件加载配置"""
        try:
            if not self.config_path.exists():
                print(f"[ConfigManager] 配置文件不存在: {self.config_path}，使用默认配置")
                self._data = self._default_config()
                self._save()
                return True

            raw = self.config_path.read_text(encoding="utf-8")

            if HAS_YAML:
                self._data = yaml.safe_load(raw) or {}
            else:
                # 无yaml库时降级为JSON
                print("[ConfigManager] ⚠️ PyYAML未安装，尝试JSON格式")
                self._data = json.loads(raw)

            self._last_load_time = time.time()
            print(f"[ConfigManager] ✅ 配置加载成功: {self.config_path}")
            return True

        except Exception as ex:
            print(f"[ConfigManager] ❌ 配置加载失败: {ex}")
            self._data = self._default_config()
            return False

    def _save(self) -> bool:
        """保存配置到YAML文件"""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            data_to_save = copy.deepcopy(self._data)

            if HAS_YAML:
                raw = yaml.dump(data_to_save, allow_unicode=True,
                                default_flow_style=False, sort_keys=False)
            else:
                raw = json.dumps(data_to_save, ensure_ascii=False, indent=2)

            self.config_path.write_text(raw, encoding="utf-8")
            print(f"[ConfigManager] 💾 配置已保存: {self.config_path}")
            return True

        except Exception as ex:
            print(f"[ConfigManager] ❌ 配置保存失败: {ex}")
            return False

    def reload(self) -> bool:
        """热重载：从磁盘重新读取配置"""
        with self._rw_lock:
            old_data = copy.deepcopy(self._data)
            success = self._load()
            if success and old_data != self._data:
                self._notify("reload", old_data, self._data)
            return success

    # ══════════════════════════════════════
    # 读取接口
    # ══════════════════════════════════════

    def get(self, key_path: str = "", default: Any = None) -> Any:
        """
        获取配置值（支持点分隔路径）
        例: get("southbound.cameras.0.ip") → "192.168.6.21"
        """
        with self._rw_lock:
            if not key_path:
                return copy.deepcopy(self._data)

            keys = key_path.split(".")
            val = self._data
            for k in keys:
                if isinstance(val, dict) and k in val:
                    val = val[k]
                elif isinstance(val, list) and k.isdigit():
                    idx = int(k)
                    val = val[idx] if idx < len(val) else default
                else:
                    return default
            return copy.deepcopy(val) if isinstance(val, (dict, list)) else val

    def get_all_masked(self) -> Dict[str, Any]:
        """获取全部配置（敏感字段脱敏）"""
        with self._rw_lock:
            return self._mask_secrets(copy.deepcopy(self._data))

    def get_southbound(self) -> Dict[str, Any]:
        """获取南向配置（摄像头+取帧器）"""
        return self.get("southbound", {})

    def get_northbound(self) -> Dict[str, Any]:
        """获取北向配置（平台+认证+心跳）"""
        return self.get("northbound", {})

    def get_device(self) -> Dict[str, Any]:
        """获取设备信息"""
        return self.get("device", {})

    def get_cameras(self) -> List[Dict[str, Any]]:
        """获取摄像头列表"""
        sb = self.get_southbound()
        return sb.get("cameras", [])

    def get_camera_by_id(self, camera_id: str) -> Optional[Dict[str, Any]]:
        """按ID查找摄像头"""
        for cam in self.get_cameras():
            if cam.get("id") == camera_id:
                return copy.deepcopy(cam)
        return None

    # ══════════════════════════════════════
    # 写入接口
    # ══════════════════════════════════════

    def set(self, key_path: str, value: Any, auto_save: bool = True) -> bool:
        """
        设置配置值（支持点分隔路径）
        例: set("northbound.hub.url", "http://x.x.x.x:8098")
        """
        with self._rw_lock:
            keys = key_path.split(".")
            old_val = self.get(key_path)

            target = self._data
            for k in keys[:-1]:
                if k not in target or not isinstance(target[k], dict):
                    target[k] = {}
                target = target[k]

            target[keys[-1]] = value

            if auto_save:
                self._save()

            self._notify(key_path, old_val, value)
            return True

    def update_southbound(self, data: Dict[str, Any], auto_save: bool = True) -> bool:
        """更新南向配置"""
        with self._rw_lock:
            old = copy.deepcopy(self._data.get("southbound", {}))
            self._data["southbound"] = self._deep_merge(old, data)
            if auto_save:
                self._save()
            self._notify("southbound", old, self._data["southbound"])
            return True

    def update_northbound(self, data: Dict[str, Any], auto_save: bool = True) -> bool:
        """更新北向配置"""
        with self._rw_lock:
            old = copy.deepcopy(self._data.get("northbound", {}))
            self._data["northbound"] = self._deep_merge(old, data)
            if auto_save:
                self._save()
            self._notify("northbound", old, self._data["northbound"])
            return True

    def add_camera(self, camera: Dict[str, Any], auto_save: bool = True) -> bool:
        """添加摄像头"""
        with self._rw_lock:
            cameras = self._data.setdefault("southbound", {}).setdefault("cameras", [])
            # 检查ID重复
            for existing in cameras:
                if existing.get("id") == camera.get("id"):
                    print(f"[ConfigManager] ⚠️ 摄像头ID已存在: {camera['id']}")
                    return False

            camera["_runtime"] = {
                "status": "offline",
                "current_mode": "none",
                "last_frame_time": "",
                "total_frames": 0,
                "errors": 0,
            }
            cameras.append(camera)
            if auto_save:
                self._save()
            self._notify("cameras/add", None, camera)
            return True

    def update_camera(self, camera_id: str, updates: Dict[str, Any], auto_save: bool = True) -> bool:
        """更新摄像头配置"""
        with self._rw_lock:
            cameras = self._data.get("southbound", {}).get("cameras", [])
            for cam in cameras:
                if cam.get("id") == camera_id:
                    old = copy.deepcopy(cam)
                    # 不允许通过此方法更新_runtime
                    updates.pop("_runtime", None)
                    cam.update(updates)
                    if auto_save:
                        self._save()
                    self._notify(f"cameras/{camera_id}", old, cam)
                    return True
            print(f"[ConfigManager] ❌ 摄像头不存在: {camera_id}")
            return False

    def remove_camera(self, camera_id: str, auto_save: bool = True) -> bool:
        """删除摄像头"""
        with self._rw_lock:
            cameras = self._data.get("southbound", {}).get("cameras", [])
            for i, cam in enumerate(cameras):
                if cam.get("id") == camera_id:
                    removed = cameras.pop(i)
                    if auto_save:
                        self._save()
                    self._notify(f"cameras/remove/{camera_id}", removed, None)
                    return True
            return False

    # ══════════════════════════════════════
    # 运行时状态更新（不触发保存到磁盘）
    # ══════════════════════════════════════

    def update_camera_runtime(self, camera_id: str, **kwargs) -> None:
        """更新摄像头运行时状态（内存 only）"""
        with self._rw_lock:
            cameras = self._data.get("southbound", {}).get("cameras", [])
            for cam in cameras:
                if cam.get("id") == camera_id:
                    rt = cam.setdefault("_runtime", {})
                    rt.update(kwargs)
                    return

    def update_platform_runtime(self, **kwargs) -> None:
        """更新平台运行时状态（内存 only）"""
        with self._rw_lock:
            nb = self._data.setdefault("northbound", {}).setdefault("_runtime", {})
            nb.update(kwargs)

    # ══════════════════════════════════════
    # 工具方法
    # ══════════════════════════════════════

    def _mask_secrets(self, obj: Any, mask: str = "******") -> Any:
        """递归脱敏敏感字段"""
        if isinstance(obj, dict):
            return {
                k: (mask if k.lower() in SENSITIVE_FIELDS else self._mask_secrets(v, mask))
                for k, v in obj.items()
            }
        elif isinstance(obj, list):
            return [self._mask_secrets(item, mask) for item in obj]
        return obj

    @staticmethod
    def _deep_merge(base: Dict, override: Dict) -> Dict:
        """深度合并字典"""
        result = copy.deepcopy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ConfigManager._deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        return result

    @staticmethod
    def _default_config() -> Dict[str, Any]:
        """返回默认配置"""
        return {
            "device": {
                "device_id": "edge-uninitialized",
                "device_name": "未初始化设备",
                "store_id": "",
                "store_name": "",
                "region": "",
                "firmware_version": "1.0.0",
                "initialized": False,
            },
            "southbound": {
                "grabber": {"mode": "auto", "buffer_size": 2},
                "cameras": [],
            },
            "northbound": {
                "hub": {"url": "", "api_key": ""},
                "auth": {"mode": "jwt", "username": "", "password": ""},
                "heartbeat": {"enabled": True, "interval_seconds": 30},
                "_runtime": {"login_status": "disconnected"},
            },
            "services": {
                "edge_ui": {"port": 9080},
                "edge_agent": {"port": 9100},
            },
        }

    # ══════════════════════════════════════
    # 变更监听器
    # ══════════════════════════════════════

    def add_listener(self, callback: Callable[[str, Any, Any], None]) -> None:
        """注册配置变更监听器"""
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[str, Any, Any], None]) -> None:
        """移除监听器"""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify(self, key: str, old_val: Any, new_val: Any) -> None:
        """通知所有监听器"""
        for listener in self._listeners:
            try:
                listener(key, old_val, new_val)
            except Exception as ex:
                print(f"[ConfigManager] 监听器异常: {ex}")

    # ══════════════════════════════════════
    # 调试/诊断
    # ══════════════════════════════════════

    def validate(self) -> List[str]:
        """校验配置完整性，返回错误列表"""
        errors = []
        d = self._data

        # 设备信息检查
        device = d.get("device", {})
        if not device.get("device_id"):
            errors.append("缺少 device.device_id")
        if not device.get("store_id"):
            errors.append("缺少 device.store_id")

        # 南向检查
        cameras = d.get("southbound", {}).get("cameras", [])
        if not cameras:
            errors.append("未配置任何摄像头")
        for i, cam in enumerate(cameras):
            if not cam.get("ip"):
                errors.append(f"摄像头[{i}]缺少IP地址")
            if not cam.get("credentials", {}).get("username"):
                errors.append(f"摄像头[{i}]缺少用户名")

        # 北向检查
        hub = d.get("northbound", {}).get("hub", {})
        if not hub.get("url"):
            errors.append("缺少 northbound.hub.url（平台地址）")

        auth = d.get("northbound", {}).get("auth", {})
        if auth.get("mode") == "jwt" and not auth.get("username"):
            errors.append("JWT模式但缺少用户名")

        return errors

    def summary(self) -> str:
        """返回配置摘要文本"""
        d = self._data
        cams = d.get("southbound", {}).get("cameras", [])
        nb_rt = d.get("northbound", {}).get("_runtime", {})

        lines = [
            f"📋 配置文件: {self.config_path}",
            f"🔧 设备: {d.get('device', {}).get('device_name', '?')} ({d.get('device', {}).get('device_id', '?')})",
            f"📷 摄像头: {len(cams)} 台",
            f"☁️ 平台: {d.get('northbound', {}).get('hub', {}).get('url', '未配置')}",
            f"❤️ 心跳: {nb_rt.get('login_status', 'unknown')} | 连续失败: {nb_rt.get('consecutive_failures', 0)}",
            f"📦 队列: {nb_rt.get('queue_depth', 0)} 条待发送",
        ]
        return "\n".join(lines)


# ══════════════════════════════════════════════════
# 全局单例访问
# ══════════════════════════════════════════════════
_config_instance: Optional[ConfigManager] = None


def get_config(config_path: Optional[str] = None) -> ConfigManager:
    """获取全局配置管理器单例"""
    global _config_instance
    if _config_instance is None:
        _config_instance = ConfigManager(config_path)
    return _config_instance


def reset_config():
    """重置单例（主要用于测试）"""
    global _config_instance
    _config_instance = None
