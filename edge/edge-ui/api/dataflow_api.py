"""
数据流管理 API (Data Flow Management API)

Edge ↔ Cloud 双向数据流接口

GET    /api/v1/dataflow/status              数据流状态总览
GET    /api/v1/dataflow/stats                详细统计信息
POST   /api/v1/dataflow/upload               手动上报数据
GET    /api/v1/dataflow/commands              拉取待执行指令
POST   /api/v1/dataflow/command/{id}/execute 执行指定指令
GET    /api/v1/dataflow/heartbeat            心跳详情
POST   /api/v1/dataflow/start                启动数据流服务
POST   /api/v1/dataflow/stop                 停止数据流服务
"""

import json
import time
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Body
from pydantic import BaseModel

# L2 PIN 认证依赖
from middleware import get_current_session

# 导入数据流管理器
from api.dataflow_manager import (
    get_dataflow_manager,
    init_dataflow,
    shutdown_dataflow,
    DataPacket,
    DataFlowType,
)

router = APIRouter()


# ── 请求/响应模型 ──

class UploadRequest(BaseModel):
    """手动上传请求"""
    type: str  # event / metric / snapshot / log
    payload: Dict[str, Any]
    store_id: Optional[str] = "store_jiaojiang"


class CommandExecuteRequest(BaseModel):
    """指令执行请求"""
    command_id: str
    parameters: Optional[Dict[str, Any]] = None


class DataFlowStatus(BaseModel):
    """数据流状态"""
    running: bool
    hub_url: str
    store_id: str
    upload_queue_depth: int
    db_pending_count: int
    stats: Dict[str, Any]
    registered_handlers: List[str]


# ── API 端点 ──

@router.get("/dataflow/status", response_model=DataFlowStatus)
async def get_dataflow_status(_=Depends(get_current_session)):
    """
    数据流状态总览

    返回:
    - 运行状态
    - 云端连接信息
    - 队列深度 (内存 + 数据库)
    - 统计信息
    - 已注册的指令处理器
    """
    manager = get_dataflow_manager()
    stats = manager.get_stats()

    return DataFlowStatus(
        running=stats["running"],
        hub_url=manager.hub_url,
        store_id=manager.store_id,
        upload_queue_depth=stats["queue_depth"],
        db_pending_count=stats["db_pending"],
        stats={
            "uploaded_total": stats.get("uploaded_total", 0),
            "uploaded_failed": stats.get("uploaded_failed", 0),
            "commands_received": stats.get("commands_received", 0),
            "commands_executed": stats.get("commands_executed", 0),
            "last_upload_time": stats.get("last_upload_time"),
            "last_command_time": stats.get("last_command_time"),
            "heartbeat_count": stats.get("heartbeat_count", 0),
            "consecutive_failures": stats.get("consecutive_failures", 0),
        },
        registered_handlers=stats.get("registered_handlers", []),
    )


@router.get("/dataflow/stats")
async def get_dataflow_stats(_=Depends(get_current_session)):
    """详细统计信息 (包含历史记录)"""
    manager = get_dataflow_manager()

    # 获取数据库中的历史记录
    import sqlite3
    from pathlib import Path

    db_path = manager.queue_db_path
    history_stats = {}

    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        try:
            # 上传队列统计
            queue_stats = conn.execute(
                "SELECT type, COUNT(*), AVG(retry_count) FROM upload_queue GROUP BY type"
            ).fetchall()
            history_stats["upload_queue_by_type"] = [
                {"type": row[0], "count": row[1], "avg_retries": round(row[2], 2) if row[2] else 0}
                for row in queue_stats
            ]

            # 指令历史统计
            cmd_stats = conn.execute(
                "SELECT command_type, status, COUNT(*) FROM command_history GROUP BY command_type, status"
            ).fetchall()
            history_stats["command_history"] = [
                {"type": row[0], "status": row[1], "count": row[2]}
                for row in cmd_stats
            ]

            # 最近10条指令
            recent_cmds = conn.execute(
                "SELECT command_id, command_type, status, executed_at FROM command_history ORDER BY id DESC LIMIT 10"
            ).fetchall()
            history_stats["recent_commands"] = [
                {
                    "command_id": row[0],
                    "type": row[1],
                    "status": row[2],
                    "executed_at": row[3],
                }
                for row in recent_cmds
            ]

        finally:
            conn.close()

    return {
        **manager.get_stats(),
        "history": history_stats,
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%S+08:00'),
    }


@router.post("/dataflow/upload")
async def manual_upload(
    request: UploadRequest,
    _=Depends(get_current_session)
):
    """
    手动上报数据

    用于测试或一次性数据上报场景
    """
    manager = get_dataflow_manager()

    # 映射类型字符串到枚举
    type_map = {
        "event": DataFlowType.EVENT,
        "metric": DataFlowType.METRIC,
        "snapshot": DataFlowType.SNAPSHOT,
        "log": DataFlowType.LOG,
    }

    flow_type = type_map.get(request.type.lower())
    if not flow_type:
        raise HTTPException(status_code=400, detail=f"不支持的数据类型: {request.type}")

    packet = DataPacket(
        type=flow_type,
        payload=request.payload,
        store_id=request.store_id or manager.store_id,
    )

    success = manager.enqueue_upload(packet)

    return {
        "code": 0 if success else -1,
        "message": "数据已入队" if success else "队列已满，已持久化",
        "type": request.type,
        "queue_depth": manager._upload_queue.qsize(),
    }


@router.get("/dataflow/commands")
async def poll_commands(_=Depends(get_current_session)):
    """
    拉取云端待执行的指令

    通常由指令工作线程自动调用，此端点用于手动触发或调试
    """
    manager = get_dataflow_manager()

    commands = manager.poll_commands()

    return {
        "code": 0,
        "message": f"拉取到 {len(commands)} 条指令",
        "commands": [
            {
                "command_id": cmd.command_id,
                "command_type": cmd.command_type,
                "payload": cmd.payload,
                "created_at": cmd.created_at,
                "expires_at": cmd.expires_at,
            }
            for cmd in commands
        ],
    }


@router.post("/dataflow/command/{command_id}/execute")
async def execute_command(
    command_id: str,
    request: Optional[CommandExecuteRequest] = None,
    _=Depends(get_current_session)
):
    """
    手动执行指定指令

    用于调试或强制重新执行场景
    """
    manager = get_dataflow_manager()

    # 构造指令对象 (简化版)
    from dataflow_manager import Command
    cmd = Command(
        command_id=command_id,
        command_type="manual",
        payload=request.parameters or {},
        created_at=time.strftime('%Y-%m-%dT%H:%M:%S+08:00'),
    )

    result = manager.execute_command(cmd)

    return {
        "code": 0,
        "message": f"指令已执行: {command_id}",
        "result": result,
    }


@router.get("/dataflow/heartbeat")
async def get_heartbeat_detail(_=Depends(get_current_session)):
    """心跳详情 (最近心跳记录和链路质量)"""
    manager = get_dataflow_manager()
    stats = manager.get_stats()

    return {
        "current_status": "online" if stats["running"] else "offline",
        "hub_url": manager.hub_url,
        "store_id": manager.store_id,
        "heartbeat": {
            "total_count": stats.get("heartbeat_count", 0),
            "interval_seconds": manager.heartbeat_interval,
            "last_heartbeat": None,  # TODO: 从实际记录获取
        },
        "link_quality": {
            "consecutive_failures": stats.get("consecutive_failures", 0),
            "status": "good" if stats.get("consecutive_failures", 0) < 3 else "degraded",
        },
        "queue_health": {
            "memory_queue_depth": stats.get("queue_depth", 0),
            "db_pending": stats.get("db_pending_count", 0),
            "status": "healthy" if stats.get("queue_depth", 0) < 500 else "backlog",
        },
    }


@router.post("/dataflow/start")
async def start_dataflow_service(_=Depends(get_current_session)):
    """启动数据流服务 (如果未运行)"""
    try:
        init_dataflow()
        return {
            "code": 0,
            "message": "数据流服务已启动",
            "hub_url": get_dataflow_manager().hub_url,
        }
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"启动失败: {ex}")


@router.post("/dataflow/stop")
async def stop_dataflow_service(_=Depends(get_current_session)):
    """停止数据流服务"""
    try:
        shutdown_dataflow()
        return {
            "code": 0,
            "message": "数据流服务已停止",
        }
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"停止失败: {ex}")


@router.post("/dataflow/test/uplink")
async def test_uplink(_=Depends(get_current_session)):
    """
    测试上行链路 (Edge → Cloud)

    发送一条测试数据并返回结果
    """
    manager = get_dataflow_manager()

    test_packet = DataPacket(
        type=DataFlowType.LOG,
        payload={
            "level": "INFO",
            "message": "Uplink test ping",
            "module": "dataflow_api",
            "test": True,
        },
    )

    # 直接尝试上传 (不入队)
    success = manager._do_upload("/dataflow/upload", {
        "type": test_packet.type.value,
        "payload": test_packet.payload,
        "timestamp": test_packet.timestamp,
        "store_id": test_packet.store_id,
        "device_id": test_packet.device_id,
        "test": True,
    })

    return {
        "code": 0 if success else -1,
        "success": success,
        "message": "上行链路测试成功" if success else "上行链路测试失败",
        "hub_url": manager.hub_url,
        "latency_ms": None,  # TODO: 实际测量
    }
