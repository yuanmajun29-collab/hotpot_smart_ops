"""
诊断工具 API
POST   /api/v1/diagnostics/run      执行完整诊断(异步)
GET    /api/v1/diagnostics/tasks/{task_id}  轮询诊断结果
"""

import time
import uuid
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel
from typing import List, Dict, Optional

# L2 PIN 认证依赖 (Step 5)
from middleware import get_current_session

router = APIRouter()

# 存储进行中的诊断任务
_diagnostic_tasks: Dict[str, Dict] = {}


class DiagnosticResult(BaseModel):
    category: str
    name: str
    target: Optional[str]
    status: str  # pass / fail / warn / error / skip
    detail: str
    timestamp: str


def _test_network(target_host: str, target_port: int, timeout: int = 5) -> DiagnosticResult:
    """测试网络连通性"""
    start = time.time()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((target_host, target_port))
        latency = int((time.time() - start) * 1000)
        sock.close()
        return DiagnosticResult(
            category="network",
            name=f"{target_host}:{target_port}",
            target=f"{target_host}:{target_port}",
            status="pass",
            detail=f"延迟 {latency}ms",
            timestamp=time.strftime('%Y-%m-%dT%H:%M:%S+08:00'),
        )
    except Exception as ex:
        return DiagnosticResult(
            category="network",
            name=f"{target_host}:{target_port}",
            target=f"{target_host}:{target_port}",
            status="fail",
            detail=str(ex),
            timestamp=time.strftime('%Y-%m-%dT%H:%M:%S+08:00'),
        )


def _test_camera(camera_config: dict) -> DiagnosticResult:
    """测试摄像头连接"""
    ip = camera_config.get("ip", "unknown")
    name = camera_config.get("name", "未知摄像头")

    # TCP测试
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((ip, 80))
        sock.close()
    except Exception as ex:
        return DiagnosticResult(
            category="camera", name=name, target=ip,
            status="fail", detail=f"TCP连接失败: {ex}",
            timestamp=time.strftime('%Y-%m-%dT%H:%M:%S+08:00'),
        )

    # HTTP测试
    try:
        from requests.auth import HTTPDigestAuth
        import requests
        http_cfg = camera_config.get("http_snapshot", {})
        creds = camera_config.get("credentials", {})
        url = f"{http_cfg.get('base_url', '')}{http_cfg.get('path', '')}"
        auth_type = http_cfg.get("auth_type", "none")

        if auth_type == "digest":
            r = requests.get(url, auth=HTTPDigestAuth(creds["username"], creds["password"]), timeout=10)
        else:
            r = requests.get(url, timeout=10)

        if r.status_code == 200 and r.content[:2] == b"\xff\xd8":
            return DiagnosticResult(
                category="camera", name=name, target=ip,
                status="pass", detail=f"抓拍成功 ({len(r.content)}B JPEG)",
                timestamp=time.strftime('%Y-%m-%dT%H:%M:%S+08:00'),
            )
        else:
            return DiagnosticResult(
                category="camera", name=name, target=ip,
                status="warn", detail=f"HTTP {r.status_code}",
                timestamp=time.strftime('%Y-%m-%dT%H:%M:%S+08:00'),
            )
    except Exception as ex:
        return DiagnosticResult(
            category="camera", name=name, target=ip,
            status="error", detail=str(ex),
            timestamp=time.strftime('%Y-%m-%dT%H:%M:%S+08:00'),
        )


def _test_system_resources() -> List[DiagnosticResult]:
    """测试系统资源"""
    results = []
    try:
        import psutil
        mem = psutil.virtual_memory()
        results.append(DiagnosticResult(
            category="resource", name="内存使用", target=None,
            status="warn" if mem.percent > 80 else "pass",
            detail=f"{mem.percent}% ({mem.used//1024//1024}MB / {mem.total//1024//1024}MB)",
            timestamp=time.strftime('%Y-%m-%dT%H:%M:%S+08:00'),
        ))

        disk = psutil.usage("/")
        results.append(DiagnosticResult(
            category="resource", name="磁盘使用", target=None,
            status="warn" if disk.percent > 90 else "pass",
            detail=f"{disk.percent}% ({disk.used//1024//1024//1024}GB / {disk.total//1024//1024//1024}GB)",
            timestamp=time.strftime('%Y-%m-%dT%H:%M:%S+08:00'),
        ))
    except Exception as ex:
        results.append(DiagnosticResult(
            category="resource", name="系统资源检测", target=None,
            status="error", detail=str(ex),
            timestamp=time.strftime('%Y-%m-%dT%H:%M:%S+08:00'),
        ))
    return results


@router.post("/diagnostics/run", status_code=202)
async def run_diagnostics(background_tasks: BackgroundTasks, _=Depends(get_current_session)):
    """
    执行完整诊断（异步）

    返回 task_id，客户端轮询 GET /tasks/{task_id} 获取结果
    """
    task_id = f"diag-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    _diagnostic_tasks[task_id] = {
        "task_id": task_id,
        "status": "running",
        "started_at": time.strftime('%Y-%m-%dT%H:%M:%S+08:00'),
        "results": [],
    }

    def _run_diagnosis():
        results = []
        # 1. 测试网络连通性
        targets = [
            ("127.0.0.1", 9080),  # Edge UI自身
            ("127.0.0.1", 9100),  # Agent
            ("43.139.143.12", 8098),  # 云端平台
        ]
        for host, port in targets:
            results.append(_test_network(host, port))

        # 2. 测试摄像头
        try:
            from api.camera_api import _load_cameras
            cameras = _load_cameras()
            for cam in cameras:
                results.append(_test_camera(cam))
        except Exception:
            results.append(DiagnosticResult(
                category="camera", name="摄像头配置", target=None,
                status="skip", detail="无法加载摄像头配置",
                timestamp=time.strftime('%Y-%m-%dT%H:%M:%S+08:00'),
            ))

        # 3. 系统资源检查
        results.extend(_test_system_resources())

        # 完成
        _diagnostic_tasks[task_id]["status"] = "completed"
        _diagnostic_tasks[task_id]["completed_at"] = time.strftime('%Y-%m-%dT%H:%M:%S+08:00')
        _diagnostic_tasks[task_id]["results"] = [r.dict() for r in results]

    background_tasks.add_task(_run_diagnosis)

    return {"task_id": task_id, "status": "running", "message": "诊断任务已启动"}


@router.get("/diagnostics/tasks/{task_id}")
async def get_diagnostic_result(task_id: str, _=Depends(get_current_session)):
    """轮询诊断结果"""
    task = _diagnostic_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"诊断任务不存在: {task_id}")

    return task
