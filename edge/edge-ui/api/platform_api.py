"""
平台状态 API (v1.1新增, 只读)

注意: 这些API只读取Agent层的状态，不直接执行登录/心跳。
实际的心跳/登录逻辑仍在 Agent (:9100) 的 hub_client.py 中。

GET /api/v1/platform/status         平台连接状态总览
GET /api/v1/platform/heartbeat-detail 心跳详情
GET /api/v1/platform/queue-status     离线队列状态
"""

import time
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends

# L2 PIN 认证依赖 (Step 5)
from middleware import get_current_session

router = APIRouter()

# 共享状态文件路径 (由 Agent 层写入)
STATE_FILE = Path("/tmp/hotpot-edge-state.json")


def _read_agent_state() -> dict:
    """读取 Agent 层写入的共享状态"""
    if STATE_FILE.exists():
        import json
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    # 返回默认值（Agent未启动或无状态文件）
    return {
        "heartbeat": {
            "enabled": True,
            "last_success_time": None,
            "success_count": 0,
            "fail_count": 0,
            "consecutive_failures": -1,  # -1 表示未知
            "history": [],
        },
        "login": {
            "status": "disconnected",
            "token_expires_at": None,
        },
        "queue": {
            "depth": -1,
            "flushed_total": 0,
            "last_flush_time": None,
        },
    }


@router.get("/platform/status")
async def get_platform_status(_=Depends(get_current_session)):
    """
    平台连接状态总览

    Edge UI 只读展示，不执行实际操作
    """
    state = _read_agent_state()
    hub_cfg = {}
    try:
        from api.config_api import _load_json
        hub_cfg = _load_json("hub_connection.json")
    except Exception:  # hub连接配置文件读取失败
        pass

    return {
        "platform": {
            "hub_url": hub_cfg.get("hub_url", "未配置"),
            "login_status": state.get("login", {}).get("status", "unknown"),
            "token_expires_at": state.get("login", {}).get("token_expires_at"),
        },
        "heartbeat": state.get("heartbeat", {}),
        "queue": state.get("queue", {}),
    }


@router.get("/platform/heartbeat-detail")
async def get_heartbeat_detail(_=Depends(get_current_session)):
    """心跳详情（最近10次历史）"""
    state = _read_agent_state()
    hb = state.get("heartbeat", {})

    current_run = None
    history = hb.get("history", [])

    if history:
        current_run = history[-1]

    return {
        "current_run": current_run,
        "history": history[-10:],  # 最近10次
        "summary": {
            "enabled": hb.get("enabled", False),
            "interval_seconds": hb.get("interval_seconds", 30),
            "total_success": hb.get("success_count", 0),
            "total_fail": hb.get("fail_count", 0),
            "consecutive_failures": hb.get("consecutive_failures", 0),
        },
    }


@router.get("/platform/queue-status")
async def get_queue_status(_=Depends(get_current_session)):
    """离线队列状态"""
    state = _read_agent_state()
    queue = state.get("queue", {})

    return {
        "depth": queue.get("depth", 0),
        "max_size": queue.get("max_size", 1000),
        "flushed_total": queue.get("flushed_total", 0),
        "last_flush_time": queue.get("last_flush_time"),
        "is_flushing": queue.get("is_flushing", False),
    }
