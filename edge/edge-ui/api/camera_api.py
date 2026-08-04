"""
摄像头管理 API (v1.1: 支持RTSP + HTTP抓拍双模式)

GET    /api/v1/cameras              摄像头列表
POST   /api/v1/cameras              添加摄像头
GET    /api/v1/cameras/{id}         摄像头详情
PUT    /api/v1/cameras/{id}         更新摄像头配置
DELETE /api/v1/cameras/{id}         删除摄像头
POST   /api/v1/cameras/{id}/reconnect 重连摄像头
GET    /api/v1/cameras/{id}/snapshot 摄像头快照(JPEG base64)
POST   /api/v1/cameras/{id}/test    测试摄像头连接
"""

import json
import time
import base64
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from typing import List, Dict, Any

# L2 PIN 认证依赖 (Step 5)
from middleware import get_current_session

router = APIRouter()

# ── 配置路径 ──
CONF_DIR = Path(__file__).parent.parent / "conf"
CAMERAS_FILE = CONF_DIR / "cameras.json"

# ── 数据模型 ──

class HttpSnapshotConfig(BaseModel):
    base_url: str
    path: str
    auth_type: str = "none"  # none / digest / basic
    avg_latency_ms: int = 0


class CameraCredentials(BaseModel):
    username: str
    password: str  # 存储时明文，API返回时脱敏


class CameraCreate(BaseModel):
    name: str
    ip: str
    vendor: str = "unknown"
    rtsp_url: Optional[str] = None
    http_snapshot: Optional[HttpSnapshotConfig] = None
    credentials: Optional[CameraCredentials] = None
    active_channel: int = 101
    resolution: str = "1920x1080"
    fps: int = 15
    codec: str = "h264"
    grabber_mode: str = "auto"  # auto / rtsp / http / mock
    purpose: str = "front_hall"
    enabled: bool = True


class CameraResponse(CameraCreate):
    id: str
    status: str = "offline"
    last_frame_time: Optional[str] = None
    created_at: str
    available_channels: List[int] = []
    _runtime: Optional[Dict[str, Any]] = None


class SnapshotResponse(BaseModel):
    image_base64: str
    size_bytes: int
    format: str = "jpeg"
    timestamp: str
    source_mode: str  # rtsp / http / mock
    latency_ms: int = 0
    camera_id: str


class TestResult(BaseModel):
    connected: bool
    tests: List[Dict[str, str]]
    resolution: Optional[str] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None


# ── 配置文件操作 ──

def _load_cameras() -> List[dict]:
    """加载摄像头配置"""
    if CAMERAS_FILE.exists():
        return json.loads(CAMERAS_FILE.read_text(encoding="utf-8")).get("cameras", [])
    return []


def _save_cameras(cameras: List[dict]):
    """保存摄像头配置"""
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    CAMERAS_FILE.write_text(json.dumps({"cameras": cameras}, ensure_ascii=False, indent=2), encoding="utf-8")


def _mask_password(camera: dict) -> dict:
    """脱敏密码字段"""
    c = dict(camera)
    if c.get("credentials") and c["credentials"].get("password"):
        c["credentials"] = {**c["credentials"], "password": "******"}
    return c


# ── 取帧方法 (HTTP抓拍) ──

def _do_http_snapshot(camera: dict) -> Optional[bytes]:
    """通过HTTP Digest认证抓取JPEG快照"""
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
        print(f"[Camera API] HTTP抓拍失败 ({camera.get('ip')}): {ex}")
        return None


# ── API 端点 ──

@router.get("/cameras", response_model=List[CameraResponse])
async def list_cameras(_=Depends(get_current_session)):
    """摄像头列表（密码脱敏）"""
    cameras = _load_cameras()
    return [_mask_password(c) for c in cameras]


@router.post("/cameras", response_model=CameraResponse, status_code=201)
async def create_camera(camera: CameraCreate, _=Depends(get_current_session)):
    """添加摄像头"""
    cameras = _load_cameras()

    new_id = f"cam_{int(time.time())}"
    now = time.strftime('%Y-%m-%dT%H:%M:%S+08:00')

    new_camera = camera.dict()
    new_camera["id"] = new_id
    new_camera["status"] = "offline"
    new_camera["created_at"] = now
    new_camera["last_frame_time"] = None
    new_camera["available_channels"] = []

    cameras.append(new_camera)
    _save_cameras(cameras)

    return _mask_password(new_camera)


@router.get("/cameras/{camera_id}", response_model=CameraResponse)
async def get_camera(camera_id: str, _=Depends(get_current_session)):
    """摄像头详情"""
    cameras = _load_cameras()
    for c in cameras:
        if c.get("id") == camera_id:
            return _mask_password(c)
    raise HTTPException(status_code=404, detail=f"摄像头不存在: {camera_id}")


@router.put("/cameras/{camera_id}", response_model=CameraResponse)
async def update_camera(camera_id: str, updates: CameraCreate, _=Depends(get_current_session)):
    """更新摄像头配置"""
    cameras = _load_cameras()
    for i, c in enumerate(cameras):
        if c.get("id") == camera_id:
            update_data = updates.dict()
            update_data.pop("id", None)  # 不允许修改ID
            update_data["created_at"] = c.get("created_at", "")
            cameras[i] = {**c, **update_data}
            _save_cameras(cameras)
            return _mask_password(cameras[i])
    raise HTTPException(status_code=404, detail=f"摄像头不存在: {camera_id}")


@router.delete("/cameras/{camera_id}")
async def delete_camera(camera_id: str, _=Depends(get_current_session)):
    """删除摄像头"""
    cameras = _load_cameras()
    for i, c in enumerate(cameras):
        if c.get("id") == camera_id:
            removed = cameras.pop(i)
            _save_cameras(cameras)
            return {"code": 0, "message": f"摄像头已删除: {removed.get('name', '')}"}
    raise HTTPException(status_code=404, detail=f"摄像头不存在: {camera_id}")


@router.post("/cameras/{camera_id}/reconnect")
async def reconnect_camera(camera_id: str, _=Depends(get_current_session)):
    """重连摄像头（重新初始化FrameGrabber）"""
    # TODO: 调用 FrameGrabber.reconnect()
    return {"code": 0, "message": f"重连请求已发送: {camera_id}"}


@router.get("/cameras/{camera_id}/snapshot", response_model=SnapshotResponse)
async def get_camera_snapshot(
    camera_id: str,
    format: str = Query(default="base64", pattern="^(base64|binary)$"),
    _=Depends(get_current_session)
):
    """
    摄像头快照

    - format=base64: 返回JSON (前端直接显示)
    - format=binary: 返回JPEG二进制流 (<img src="..."> 直接使用)
    """
    cameras = _load_cameras()
    target = None
    for c in cameras:
        if c.get("id") == camera_id:
            target = c
            break

    if not target:
        raise HTTPException(status_code=404, detail=f"摄像头不存在: {camera_id}")

    # 尝试HTTP抓拍
    start = time.time()
    img_data = _do_http_snapshot(target)
    latency = int((time.time() - start) * 1000)

    if img_data:
        img_b64 = base64.b64encode(img_data).decode()
        return SnapshotResponse(
            image_base64=img_b64,
            size_bytes=len(img_data),
            timestamp=time.strftime('%Y-%m-%d %H:%M:%S'),
            source_mode="http",
            latency_ms=latency,
            camera_id=camera_id,
        )

    # ⚠️ 生产模式: 不再降级到Mock，直接返回错误
    # 改造方案要求: 移除椒江生产配置中的 demo 图片和 mock 降级
    raise HTTPException(
        status_code=503,
        detail="无法获取图像（摄像头离线或网络不可达）。生产环境已禁用Mock降级。"
    )


@router.post("/cameras/{camera_id}/test", response_model=TestResult)
async def test_camera_connection(camera_id: str, _=Depends(get_current_session)):
    """测试摄像头全链路连接(IP→端口→HTTP→Auth)"""
    cameras = _load_cameras()
    target = None
    for c in cameras:
        if c.get("id") == camera_id:
            target = c
            break

    if not target:
        raise HTTPException(status_code=404, detail=f"摄像头不存在: {camera_id}")

    import socket
    tests = []
    ip = target.get("ip", "")

    # 测试1: TCP连通性
    try:
        start = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((ip, 80))
        latency = int((time.time() - start) * 1000)
        sock.close()
        tests.append({"target": f"TCP {ip}:80", "status": "pass", "detail": f"{latency}ms"})
    except Exception as ex:
        tests.append({"target": f"TCP {ip}:80", "status": "fail", "detail": str(ex)})
        return TestResult(connected=False, tests=tests)

    # 测试2: HTTP端点可达性
    try:
        import requests
        http_cfg = target.get("http_snapshot", {})
        url = f"{http_cfg.get('base_url', '')}{http_cfg.get('path', '')}"
        start = time.time()
        r = requests.get(url, timeout=10, allow_redirects=False)
        latency = int((time.time() - start) * 1000)
        status = "pass" if r.status_code in [200, 401] else "warn"  # 401说明端点可达只是需要认证
        tests.append({"target": "HTTP Endpoint", "status": status, "detail": f"{r.status_code} ({len(r.content)}B)"})
    except Exception as ex:
        tests.append({"target": "HTTP Endpoint", "status": "fail", "detail": str(ex)})
        return TestResult(connected=False, tests=tests)

    # 测试3: 认证
    try:
        from requests.auth import HTTPDigestAuth
        creds = target.get("credentials", {})
        http_cfg = target.get("http_snapshot", {})
        url = f"{http_cfg.get('base_url', '')}{http_cfg.get('path', '')}"
        auth_type = http_cfg.get("auth_type", "none")

        if auth_type == "digest":
            r = requests.get(url, auth=HTTPDigestAuth(creds["username"], creds["password"]), timeout=10)
        elif auth_type == "basic":
            r = requests.get(url, auth=(creds["username"], creds["password"]), timeout=10)
        else:
            r = requests.get(url, timeout=10)

        if r.status_code == 200 and r.content[:2] == b"\xff\xd8":
            tests.append({"target": "Digest Auth", "status": "pass", "detail": f"认证成功 ({len(r.content)}B JPEG)"})
            return TestResult(
                connected=True,
                tests=tests,
                resolution="704x576",  # TODO: 实际解析
                latency=latency,
            )
        else:
            tests.append({"target": "Digest Auth", "status": "fail", "detail": f"返回 {r.status_code}"})
    except Exception as ex:
        tests.append({"target": "Digest Auth", "status": "fail", "detail": str(ex)})

    return TestResult(connected=False, tests=tests)
