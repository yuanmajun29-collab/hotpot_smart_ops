"""
引擎状态 API
GET /api/v1/engines/status       五大引擎状态汇总
GET /api/v1/engines/{name}/status 单个引擎详情
POST /api/v1/engines/{name}/restart 重启单个引擎
GET /api/v1/engines/{name}/logs  引擎日志(最后100行)
"""

import time
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional

# L2 PIN 认证依赖 (Step 5)
from middleware import get_current_session

router = APIRouter()


# MVP阶段返回静态引擎列表（后续从Agent层获取实时状态）
ENGINES = [
    {
        "name": "front_hall_infer",
        "display_name": "前厅视觉",
        "status": "running",
        "fps": 12.3,
        "pid": 12345,
        "port": 9101,
        "uptime_seconds": 1728000,
        "last_error": None,
        "model": "YOLOv8n-FoodSafety-v2.1",
    },
    {
        "name": "kitchen_vlm",
        "display_name": "后厨VLM",
        "status": "running",
        "fps": 8.1,
        "pid": 12346,
        "port": 9102,
        "uptime_seconds": 1719000,
        "last_error": None,
        "model": "Qwen-VL-Chat-v1.1",
    },
    {
        "name": "receiving_infer",
        "display_name": "收货检测",
        "status": "idle",
        "fps": 0,
        "pid": 12347,
        "port": 9103,
        "uptime_seconds": 1720000,
        "last_error": None,
        "model": "YOLOv8n-Detect-v2.0",
    },
    {
        "name": "iot_bridge",
        "display_name": "IoT桥接",
        "status": "running",
        "sensors_online": 5,
        "sensors_total": 6,
        "pid": 12348,
        "port": 9104,
    },
    {
        "name": "frame_grabber",
        "display_name": "取帧引擎",
        "status": "running",
        "mode": "http",
        "fps": 6.0,
        "camera_id": "cam_a1_main",
        "total_frames": 152340,
        "errors": 3,
    },
]


@router.get("/engines/status")
async def get_engines_status(_=Depends(get_current_session)):
    """五大引擎状态汇总"""
    return {"engines": ENGINES, "total": len(ENGINES), "running": sum(1 for e in ENGINES if e.get("status") == "running")}


@router.get("/engines/{engine_name}/status")
async def get_engine_status(engine_name: str, _=Depends(get_current_session)):
    """单个引擎详情"""
    for e in ENGINES:
        if e.get("name") == engine_name:
            return e
    raise HTTPException(status_code=404, detail=f"引擎不存在: {engine_name}")


@router.post("/engines/{engine_name}/restart")
async def restart_engine(engine_name: str, _=Depends(get_current_session)):
    """重启单个引擎"""
    # TODO: 向 Agent 发送重启信号
    return {"code": 0, "message": f"重启请求已发送: {engine_name}"}


@router.get("/engines/{engine_name}/logs")
async def get_engine_logs(engine_name: str, tail: int = 100, _=Depends(get_current_session)):
    """引擎日志(最后N行)"""
    # MVP阶段返回模拟日志
    logs = []
    for i in range(min(tail, 100)):
        ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() - i * 60))
        messages = [
            f"[{engine_name}] 推理帧处理完成: 1920x1080, 耗时 {80 + i % 20}ms",
            f"[{engine_name}] 检测到目标: confidence={0.85 + (i % 15) / 100:.2f}",
            f"[{engine_name}] 模型加载完成: YOLOv8n",
            f"[{engine_name}] GPU显存: {1500 + i * 10}MB / 8192MB",
            f"[{engine_name}] 帧队列深度: {2 + i % 5}",
        ]
        levels = ["INFO", "DEBUG", "WARN", "ERROR"]
        logs.append({
            "timestamp": ts,
            "level": levels[i % len(levels)],
            "source": engine_name,
            "message": messages[i % len(messages)],
        })
    return {"engine_name": engine_name, "tail": tail, "logs": logs}
