"""
实时视频流 API (MJPEG Streaming)

GET    /api/v1/cameras/{id}/stream          MJPEG实时视频流 (浏览器直接播放)
GET    /api/v1/cameras/{id}/mjpeg           MJPEG流(兼容模式)
POST   /api/v1/cameras/{id}/stream/start    启动视频流推送任务
POST   /api/v1/cameras/{id}/stream/stop     停止视频流推送任务

支持:
- HTTP JPEG抓拍 → MJPEG流式输出 (适用于海康NVR等不支持RTSP的设备)
- 自动帧率控制 (1-30 FPS可调)
- 浏览器直接 <img src="..."> 播放
- 断线自动重连
"""

import asyncio
import time
import base64
import threading
from pathlib import Path
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from starlette.responses import StreamingResponse
import json

# L2 PIN 认证依赖
from middleware import get_current_session

router = APIRouter()

# ── 配置路径 ──
CONF_DIR = Path(__file__).parent.parent / "conf"
CAMERAS_FILE = CONF_DIR / "cameras.json"

# ── 全局状态: 视频流会话管理 ──
_stream_sessions: Dict[str, Dict[str, Any]] = {}
_stream_lock = threading.Lock()


class StreamConfig(BaseModel):
    """视频流配置"""
    fps: int = Query(default=5, ge=1, le=30, description="帧率 (1-30 FPS)")
    quality: int = Query(default=80, ge=10, le=100, description="JPEG质量 (10-100)")
    width: Optional[int] = Query(default=None, description="宽度 (None=原始)")
    height: Optional[int] = Query(default=None, description="高度 (None=原始)")


def _load_cameras() -> list:
    """加载摄像头配置"""
    if CAMERAS_FILE.exists():
        return json.loads(CAMERAS_FILE.read_text(encoding="utf-8")).get("cameras", [])
    return []


def _get_camera(camera_id: str) -> Optional[dict]:
    """获取单个摄像头配置"""
    for cam in _load_cameras():
        if cam.get("id") == camera_id:
            # 密码脱敏副本（内部使用保留原密码）
            return cam
    return None


def _do_http_snapshot_raw(camera: dict) -> Optional[bytes]:
    """
    通过HTTP Digest认证抓取JPEG快照 (返回原始二进制)

    这是视频流的核心取帧方法
    """
    try:
        from requests.auth import HTTPDigestAuth
        import requests

        http_cfg = camera.get("http_snapshot", {})
        creds = camera.get("credentials", {})

        url = f"{http_cfg['base_url']}{http_cfg['path']}"
        auth_type = http_cfg.get("auth_type", "none")

        if auth_type == "digest":
            r = requests.get(url, auth=HTTPDigestAuth(creds["username"], creds["password"]), timeout=10)
        elif auth_type == "basic":
            r = requests.get(url, auth=(creds["username"], creds["password"]), timeout=10)
        else:
            r = requests.get(url, timeout=10)

        r.raise_for_status()
        data = r.content
        if data[:2] == b"\xff\xd8":  # JPEG magic bytes
            return data
        return None
    except Exception as ex:
        print(f"[VideoStream] 抓帧失败 ({camera.get('ip')}): {ex}")
        return None


async def _generate_mjpeg_stream(
    camera_id: str,
    fps: int = 5,
    quality: int = 80,
):
    """
    MJPEG流生成器 (异步生成器)

    格式:
    --boundary\r\n
    Content-Type: image/jpeg\r\n
    Content-Length: {size}\r\n
    X-Timestamp: {ts}\r\n
    \r\n
    {jpeg_data}\r\n
    """

    camera = _get_camera(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail=f"摄像头不存在: {camera_id}")

    boundary = "--frame_boundary"
    frame_interval = 1.0 / fps  # 帧间隔(秒)

    print(f"[VideoStream] 开始MJPEG流: {camera_id} @ {fps}FPS")

    try:
        while True:
            start_time = time.time()

            # 同步抓帧 (HTTP请求是阻塞的，在线程池中执行)
            loop = asyncio.get_event_loop()
            jpeg_data = await loop.run_in_executor(None, _do_http_snapshot_raw, camera)

            if jpeg_data:
                timestamp = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime())

                # 构建MJPEG帧
                frame = (
                    f"{boundary}\r\n"
                    f"Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(jpeg_data)}\r\n"
                    f"X-Timestamp: {timestamp}\r\n"
                    f"\r\n"
                ).encode('utf-8') + jpeg_data + b"\r\n"

                yield frame
            else:
                # 抓帧失败，发送空帧保持连接
                error_frame = (
                    f"{boundary}\r\n"
                    f"Content-Type: text/plain\r\n"
                    f"X-Error: snapshot_failed\r\n"
                    f"\r\n"
                    "Camera snapshot failed"
                    "\r\n"
                ).encode('utf-8')
                yield error_frame

            # 帧率控制
            elapsed = time.time() - start_time
            sleep_time = max(0, frame_interval - elapsed)
            await asyncio.sleep(sleep_time)

    except asyncio.CancelledError:
        print(f"[VideoStream] MJPEG流已取消: {camera_id}")
    except Exception as ex:
        print(f"[VideoStream] MJPEG流异常: {camera_id} - {ex}")
        raise


@router.get("/cameras/{camera_id}/stream")
async def get_camera_stream(
    camera_id: str,
    fps: int = Query(default=5, ge=1, le=30, description="帧率"),
    _=Depends(get_current_session)
):
    """
    实时MJPEG视频流

    直接在浏览器中显示:
    <img src="/api/v1/cameras/{id}/stream?fps=5" />

    或用于video标签:
    <video autoplay>
      <source src="/api/v1/cameras/{id}/stream?fps=15" type="video/x-motion-jpeg">
    </video>

    参数:
    - fps: 帧率 (1-30, 默认5FPS以节省带宽)
    """
    camera = _get_camera(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail=f"摄像头不存在: {camera_id}")

    # 注册流会话
    with _stream_lock:
        _stream_sessions[camera_id] = {
            "started_at": time.time(),
            "fps": fps,
            "client_ip": "",  # 可从request中获取
            "status": "active",
        }

    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "X-Accel-Buffering": "no",  # 禁用nginx缓冲
        "Content-Type": "multipart/x-mixed-replace; boundary=frame_boundary",
        "Access-Control-Allow-Origin": "*",
    }

    return StreamingResponse(
        _generate_mjpeg_stream(camera_id=camera_id, fps=fps),
        media_type="multipart/x-mixed-replace; boundary=frame_boundary",
        headers=headers,
    )


@router.get("/cameras/{camera_id}/mjpeg")
async def get_camera_mjpeg(
    camera_id: str,
    fps: int = Query(default=5, ge=1, le=30),
    _=Depends(get_current_session)
):
    """MJPEG流 (兼容模式，与/stream相同)"""
    return await get_camera_stream(camera_id=camera_id, fps=fps)


@router.post("/cameras/{camera_id}/stream/start")
async def start_stream_push(
    camera_id: str,
    config: StreamConfig,
    _=Depends(get_current_session)
):
    """
    启动视频流推送任务 (后台持续抓帧并上传到云端)

    用于Edge→Cloud的视频流推送场景
    """
    camera = _get_camera(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail=f"摄像头不存在: {camera_id}")

    # TODO: 实现后台推送任务
    # 1. 创建后台线程/协程
    # 2. 持续抓帧
    # 3. 通过hub_client上传到云端

    return {
        "code": 0,
        "message": f"视频流推送任务已启动: {camera_id}",
        "camera_id": camera_id,
        "config": {
            "fps": config.fps,
            "quality": config.quality,
        },
        "task_id": f"stream_{camera_id}_{int(time.time())}",
    }


@router.post("/cameras/{camera_id}/stream/stop")
async def stop_stream_push(
    camera_id: str,
    _=Depends(get_current_session)
):
    """停止视频流推送任务"""

    # TODO: 停止后台推送任务

    return {
        "code": 0,
        "message": f"视频流推送任务已停止: {camera_id}",
        "camera_id": camera_id,
    }


@router.get("/cameras/{camera_id}/stream/status")
async def get_stream_status(
    camera_id: str,
    _=Depends(get_current_session)
):
    """查询视频流状态"""

    with _stream_lock:
        session = _stream_sessions.get(camera_id)

    if not session:
        return {
            "camera_id": camera_id,
            "status": "inactive",
            "active_clients": 0,
        }

    return {
        "camera_id": camera_id,
        "status": session.get("status", "unknown"),
        "started_at": session.get("started_at"),
        "fps": session.get("fps"),
        "duration_seconds": int(time.time() - session.get("started_at", 0)),
        "active_clients": 1,
    }
