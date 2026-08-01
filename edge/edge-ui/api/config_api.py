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
from pathlib import Path
from typing import Any, Dict
from fastapi import APIRouter, HTTPException, Depends
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
