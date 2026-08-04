"""
配置管理 API (v1.1新增)

GET    /api/v1/config              获取全部配置(脱敏)
PUT    /api/v1/config/device        更新设备配置
PUT    /api/v1/config/cameras      更新摄像头配置
PUT    /api/v1/config/hub          更新Hub连接配置
POST   /api/v1/config/reload        热重载配置
"""

import json
import copy
import hashlib
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, List
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

# L2 PIN 认证依赖 (Step 5)
from middleware import get_current_session

router = APIRouter()

CONF_DIR = Path(__file__).parent.parent / "conf"

# ── 敏感字段列表 ──
SENSITIVE_FIELDS = {"password", "pwd", "secret", "token", "api_key"}


def _mask_secrets(obj: Any, mask: str = "******") -> Any:
    """递归脱敏敏感字段"""
    if isinstance(obj, dict):
        return {k: (mask if k.lower() in SENSITIVE_FIELDS else _mask_secrets(v, mask)) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_mask_secrets(item, mask) for item in obj]
    return obj


def _load_json(filename: str) -> Dict:
    """加载JSON配置文件"""
    path = CONF_DIR / filename
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_json(filename: str, data: Dict):
    """保存JSON配置文件"""
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    (CONF_DIR / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@router.get("/config")
async def get_all_config(_=Depends(get_current_session)):
    """
    获取全部配置（敏感字段自动脱敏）
    返回合并后的完整配置树
    """
    config = {
        "device": _load_json("device.json"),
        "cameras": _load_json("cameras.json"),
        "hub_connection": _load_json("hub_connection.json"),
        "ui_settings": _load_json("ui_settings.json"),
    }
    return _mask_secrets(config)


@router.put("/config/device")
async def update_device_config(data: Dict[str, Any], _=Depends(get_current_session)):
    """更新设备基本信息"""
    existing = _load_json("device.json")
    existing.update(data)
    # 保护只读字段
    existing.pop("device_id", None)
    existing.pop("created_at", None)
    _save_json("device.json", existing)
    return {"code": 0, "message": "设备配置已保存"}


@router.put("/config/cameras")
async def update_cameras_config(data: Dict[str, Any], _=Depends(get_current_session)):
    """批量更新摄像头配置"""
    _save_json("cameras.json", data)
    camera_list = data.get("cameras", [])
    return {"code": 0, "message": f"摄像头配置已保存 ({len(camera_list)} 台)"}


@router.put("/config/hub")
async def update_hub_config(data: Dict[str, Any], _=Depends(get_current_session)):
    """更新Hub连接（平台）配置"""
    existing = _load_json("hub_connection.json")
    existing.update(data)
    _save_json("hub_connection.json", existing)
    return {"code": 0, "message": "平台连接配置已保存"}


@router.post("/config/reload")
async def reload_config(_=Depends(get_current_session)):
    """热重载：从磁盘重新读取所有配置（通知FrameGrabber等组件）"""
    # TODO: 发送事件通知各组件重新加载
    config = {
        "device": _load_json("device.json"),
        "cameras": _load_json("cameras.json"),
        "hub_connection": _load_json("hub_connection.json"),
    }
    return {
        "code": 0,
        "message": "配置已热重载",
        "reloaded_at": __import__("time").strftime('%Y-%m-%dT%H:%M:%S+08:00'),
        "config_masked": _mask_secrets(config),
    }


# ══════════════════════════════════════════════════════════
# P1-03: 配置热加载通知机制
# ══════════════════════════════════════════════════════════

class ConfigChangeNotifier:
    """配置变更通知器

    功能:
    - 计算配置文件内容哈希 (SHA256) 检测变更
    - 维护配置版本号 (每次变更自增)
    - 变更订阅者列表 (WebSocket/长轮询场景预留)
    - 变更前后 Diff 对比
    """

    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self._config_hashes: Dict[str, str] = {}  # file_path -> sha256
        self._config_versions: Dict[str, int] = {}  # file_path -> version int
        self._change_log: List[Dict] = []  # 变更日志
        self._subscribers: Dict[str, List] = defaultdict(list)  # config_key -> callbacks
        self._max_log = 100

    @classmethod
    def get_instance(cls) -> 'ConfigChangeNotifier':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def compute_hash(self, content: str) -> str:
        """计算配置内容 SHA256 哈希"""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]

    def snapshot(self, config_key: str, content: str):
        """记录配置快照 (初始加载时调用)"""
        h = self.compute_hash(content)
        self._config_hashes[config_key] = h
        self._config_versions.setdefault(config_key, 0)

    def detect_change(self, config_key: str, new_content: str) -> Optional[Dict]:
        """检测配置是否发生变更

        Returns:
            None 如果无变更, 否则返回变更详情
        """
        new_hash = self.compute_hash(new_content)
        old_hash = self._config_hashes.get(config_key)

        if old_hash == new_hash:
            return None

        # 有变更
        old_version = self._config_versions.get(config_key, 0)
        new_version = old_version + 1
        self._config_hashes[config_key] = new_hash
        self._config_versions[config_key] = new_version

        change_record = {
            "config_key": config_key,
            "old_hash": old_hash or "initial",
            "new_hash": new_hash,
            "version": new_version,
            "previous_version": old_version,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "detected_by": "api_call",  # api_call / poll / watchdog
        }
        self._change_log.append(change_record)
        if len(self._change_log) > self._max_log:
            self._change_log = self._change_log[-self._max_log:]

        return change_record

    def get_version(self, config_key: str) -> int:
        """获取当前配置版本号"""
        return self._config_versions.get(config_key, 0)

    def get_change_log(self, since_version: Optional[int] = None, limit: int = 20) -> List[Dict]:
        """获取变更日志"""
        log = self._change_log
        if since_version is not None:
            log = [c for c in log if c.get("version", 0) > since_version]
        return log[-limit:]

    def get_status(self) -> Dict:
        """获取所有被追踪的配置状态"""
        return {
            key: {
                "current_hash": h,
                "version": self._config_versions.get(key, 0),
                "last_modified": max(
                    (c["timestamp"] for c in self._change_log if c["config_key"] == key),
                    default="unknown",
                ),
            }
            for key, h in self._config_hashes.items()
        }


# 全局单例
config_notifier = ConfigChangeNotifier.get_instance()


# ── 新增 API 端点 ──

class ConfigDiffResponse(BaseModel):
    config_key: str
    version: int
    previous_version: int
    changed: bool
    hash_before: Optional[str]
    hash_after: str
    timestamp: str


class ConfigStatusResponse(BaseModel):
    tracked_configs: Dict
    total_changes: int
    recent_changes: List[Dict]


@router.get("/config/status", response_model=ConfigStatusResponse)
async def get_config_status(_=Depends(get_current_session)):
    """获取所有配置文件的版本和变更状态"""
    status = config_notifier.get_status()
    recent = config_notifier.get_change_log(limit=10)
    return ConfigStatusResponse(
        tracked_configs=status,
        total_changes=len(config_notifier._change_log),
        recent_changes=recent,
    )


@router.get("/config/{config_key}/version")
async def get_config_version(config_key: str, _=Depends(get_current_session)):
    """获取指定配置的当前版本号"""
    version = config_notifier.get_version(config_key)
    return {"config_key": config_key, "version": version}


@router.get("/config/change-log")
async def get_config_change_log(
    since: Optional[int] = Query(default=None, description="起始版本号"),
    limit: int = Query(default=20, ge=1, le=100),
    _=Depends(get_current_session),
):
    """获取配置变更日志"""
    changes = config_notifier.get_change_log(since_version=since, limit=limit)
    return {"total": len(changes), "changes": changes}


@router.post("/config/{config_key}/snapshot")
async def snapshot_config(config_key: str, body: Dict[str, Any], _=Depends(get_current_session)):
    """手动记录配置快照 (用于初始注册或强制刷新)"""
    import json
    content = json.dumps(body, ensure_ascii=False, sort_keys=True)
    config_notifier.snapshot(config_key, content)
    version = config_notifier.get_version(config_key)
    return {
        "config_key": config_key,
        "version": version,
        "hash": config_notifier.compute_hash(content),
        "message": "快照已记录",
    }


@router.post("/config/{config_key}/diff", response_model=ConfigDiffResponse)
async def diff_config(
    config_key: str,
    body: Dict[str, Any],
    _=Depends(get_current_session)
):
    """检测配置变更并返回差异信息"""
    import json
    content = json.dumps(body, ensure_ascii=False, sort_keys=True)
    change = config_notifier.detect_change(config_key, content)

    if change is None:
        return ConfigDiffResponse(
            config_key=config_key,
            version=config_notifier.get_version(config_key),
            previous_version=config_notifier.get_version(config_key),
            changed=False,
            hash_after=config_notifier.compute_hash(content),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    return ConfigDiffResponse(
        config_key=config_key,
        version=change["version"],
        previous_version=change["previous_version"],
        changed=True,
        hash_before=change["old_hash"],
        hash_after=change["new_hash"],
        timestamp=change["timestamp"],
    )
