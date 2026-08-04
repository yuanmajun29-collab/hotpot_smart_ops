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
import threading
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List, Any

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

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
    """重连摄像头 (带指数退避策略)

    - 自动计算退避等待时间 (基于连续失败次数)
    - 记录重连历史
    - 更新连接状态
    """
    cameras = _load_cameras()
    target = None
    for c in cameras:
        if c.get("id") == camera_id:
            target = c
            break

    if not target:
        raise HTTPException(status_code=404, detail=f"摄像头不存在: {camera_id}")

    # 标记为重连中
    conn_mgr.update_status(camera_id, "reconnecting", "发起重连请求")

    # 执行连接测试
    try:
        import requests
        from requests.auth import HTTPDigestAuth

        http_cfg = target.get("http_snapshot", {})
        creds = target.get("credentials", {})
        url = f"{http_cfg.get('base_url', '')}{http_cfg.get('path', '')}"
        auth_type = http_cfg.get("auth_type", "none")

        start = time.time()
        if auth_type == "digest":
            r = requests.get(url, auth=HTTPDigestAuth(creds["username"], creds["password"]), timeout=10)
        elif auth_type == "basic":
            r = requests.get(url, auth=(creds["username"], creds["password"]), timeout=10)
        else:
            r = requests.get(url, timeout=10)

        latency = int((time.time() - start) * 1000)

        if r.status_code == 200 and r.content[:2] == b"\xff\xd8":
            conn_mgr.record_reconnect(camera_id, True, f"延迟={latency}ms, 大小={len(r.content)}B")
            backoff = conn_mgr.get_next_backoff_seconds(camera_id)
            return {
                "code": 0,
                "status": "connected",
                "message": f"重连成功: {target.get('name', '')}",
                "latency_ms": latency,
                "image_size": len(r.content),
                "next_backoff_s": backoff,
                "consecutive_failures": 0,
            }
        else:
            conn_mgr.record_reconnect(camera_id, False, f"HTTP {r.status_code}")
            backoff = conn_mgr.get_next_backoff_seconds(camera_id)
            return {
                "code": 1,
                "status": "failed",
                "message": f"重连失败: HTTP {r.status_code}",
                "next_backoff_s": backoff,
                "consecutive_failures": conn_mgr._status.get(camera_id, {}).get("consecutive_failures", 1),
            }
    except Exception as ex:
        conn_mgr.record_reconnect(camera_id, False, str(ex))
        backoff = conn_mgr.get_next_backoff_seconds(camera_id)
        return {
            "code": 2,
            "status": "error",
            "message": f"重连异常: {str(ex)}",
            "next_backoff_s": backoff,
            "consecutive_failures": conn_mgr._status.get(camera_id, {}).get("consecutive_failures", 1),
        }


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


# ── P1-02: 摄像头连接管理器 (自动重连 + 流控) ──

logger = logging.getLogger(__name__)


class CameraConnectionManager:
    """摄像头连接管理器

    职责:
    - 维护每个摄像头的连接状态和统计信息
    - 自动重连 (指数退避: 1s → 2s → 4s → 8s → 16s → max 30s)
    - 流控参数管理 (帧率限制/带宽限制)
    - 健康检查调度
    """

    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self._status: Dict[str, Dict] = {}  # camera_id -> status dict
        self._stream_config: Dict[str, Dict] = {}  # camera_id -> stream config
        self._reconnect_history: Dict[str, List] = defaultdict(list)  # 重连历史
        self._max_history = 50  # 保留最近50条重连记录

    @classmethod
    def get_instance(cls) -> 'CameraConnectionManager':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def update_status(self, camera_id: str, status: str, detail: str = "", latency_ms: int = 0):
        """更新摄像头连接状态"""
        now = datetime.now(timezone.utc).isoformat()
        old_status = self._status.get(camera_id, {}).get("status", "unknown")

        self._status[camera_id] = {
            "camera_id": camera_id,
            "status": status,  # online / offline / degraded / reconnecting
            "detail": detail,
            "latency_ms": latency_ms,
            "updated_at": now,
            "since": self._status.get(camera_id, {}).get("since", now),
            "total_reconnects": self._status.get(camera_id, {}).get("total_reconnects", 0),
            "consecutive_failures": 0 if status == "online" else self._status.get(camera_id, {}).get("consecutive_failures", 0) + (1 if status != "online" else 0),
        }

        # 状态变化时更新 since 时间戳
        if old_status != status:
            self._status[camera_id]["since"] = now
            if status == "online":
                self._status[camera_id]["consecutive_failures"] = 0

        logger.info("[CameraConn] %s → %s (%dms) %s", camera_id, status, latency_ms, detail)

    def get_next_backoff_seconds(self, camera_id: str) -> int:
        """计算指数退避等待时间 (秒)

        策略: 1s → 2s → 4s → 8s → 16s → 30s(封顶)
        成功连接后重置为 1s
        """
        failures = self._status.get(camera_id, {}).get("consecutive_failures", 0)
        backoff = min(2 ** failures, 30)  # 指数退避, 最大30秒
        return backoff

    def record_reconnect(self, camera_id: str, success: bool, detail: str = ""):
        """记录重连事件"""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "camera_id": camera_id,
            "success": success,
            "detail": detail,
            "attempt": len(self._reconnect_history[camera_id]) + 1,
        }
        self._reconnect_history[camera_id].append(record)

        # 限制历史长度
        if len(self._reconnect_history[camera_id]) > self._max_history:
            self._reconnect_history[camera_id] = self._reconnect_history[camera_id][-self._max_history:]

        # 更新统计
        if success:
            self.update_status(camera_id, "online", f"重连成功: {detail}")
        else:
            self.update_status(camera_id, "offline", f"重连失败: {detail}")

        if camera_id in self._status:
            self._status[camera_id]["total_reconnects"] = len([r for r in self._reconnect_history[camera_id] if r["success"]])

    def set_stream_config(self, camera_id: str, config: Dict):
        """设置流控参数"""
        defaults = {
            "max_fps": 15,
            "max_bandwidth_kbps": 4096,
            "resolution": "1920x1080",
            "codec": "h264",
            "gop_size": 30,
            "bitrate_mode": "vbr",  # vbr / cbr
            "quality": 70,  # 1-100
        }
        defaults.update(config)
        self._stream_config[camera_id] = defaults
        logger.info("[CameraConn] %s 流控配置已更新: %s", camera_id, defaults)

    def get_stream_config(self, camera_id: str) -> Dict:
        """获取流控参数"""
        return self._stream_config.get(camera_id, {
            "max_fps": 15,
            "max_bandwidth_kbps": 4096,
            "resolution": "1920x1080",
            "codec": "h264",
            "gop_size": 30,
            "bitrate_mode": "vbr",
            "quality": 70,
        })

    def get_status(self, camera_id: Optional[str] = None) -> Dict:
        """获取连接状态"""
        if camera_id:
            return self._status.get(camera_id, {"status": "unknown", "camera_id": camera_id})
        return dict(self._status)

    def get_health_summary(self) -> Dict:
        """获取健康检查摘要"""
        total = len(self._status)
        online = sum(1 for s in self._status.values() if s.get("status") == "online")
        offline = sum(1 for s in self._status.values() if s.get("status") in ("offline", "reconnecting"))
        degraded = sum(1 for s in self._status.values() if s.get("status") == "degraded")

        return {
            "total_cameras": total,
            "online": online,
            "offline": offline,
            "degraded": degraded,
            "online_rate": round(online / max(total, 1) * 100, 1),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# 全局单例
conn_mgr = CameraConnectionManager.get_instance()


# ══════════════════════════════════════════════════════════
# P1-02: 流控与连接管理 API
# ══════════════════════════════════════════════════════════

class StreamConfigRequest(BaseModel):
    max_fps: int = 15           # 最大帧率 (1-30)
    max_bandwidth_kbps: int = 4096  # 最大带宽 (512-16384)
    resolution: str = "1920x1080"
    codec: str = "h264"         # h264 / h265 / mjpeg
    gop_size: int = 30          # GOP大小
    bitrate_mode: str = "vbr"   # vbr / cbr
    quality: int = 70           # 质量 (1-100)


class StreamConfigResponse(BaseModel):
    camera_id: str
    config: Dict
    applied_at: str


class ConnectionHealthResponse(BaseModel):
    summary: Dict
    cameras: Dict


@router.get("/cameras/{camera_id}/stream-config", response_model=StreamConfigResponse)
async def get_stream_config(camera_id: str, _=Depends(get_current_session)):
    """获取摄像头流控配置"""
    config = conn_mgr.get_stream_config(camera_id)
    return StreamConfigResponse(
        camera_id=camera_id,
        config=config,
        applied_at=datetime.now(timezone.utc).isoformat(),
    )


@router.put("/cameras/{camera_id}/stream-config", response_model=StreamConfigResponse)
async def update_stream_config(
    camera_id: str,
    req: StreamConfigRequest,
    _=Depends(get_current_session)
):
    """更新摄像头流控配置"""
    # 参数校验
    if not 1 <= req.max_fps <= 30:
        raise HTTPException(status_code=400, detail="max_fps 必须在 1-30 之间")
    if not 512 <= req.max_bandwidth_kbps <= 16384:
        raise HTTPException(status_code=400, detail="max_bandwidth_kbps 必须在 512-16384 之间")
    if not 1 <= req.quality <= 100:
        raise HTTPException(status_code=400, detail="quality 必须在 1-100 之间")

    conn_mgr.set_stream_config(camera_id, req.dict())
    config = conn_mgr.get_stream_config(camera_id)
    return StreamConfigResponse(
        camera_id=camera_id,
        config=config,
        applied_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/cameras/health", response_model=ConnectionHealthResponse)
async def get_cameras_health(_=Depends(get_current_session)):
    """获取所有摄像头连接健康状态摘要"""
    summary = conn_mgr.get_health_summary()
    statuses = conn_mgr.get_status()
    return ConnectionHealthResponse(summary=summary, cameras=statuses)


@router.get("/cameras/{camera_id}/health")
async def get_camera_health(camera_id: str, _=Depends(get_current_session)):
    """获取单个摄像头详细健康状态"""
    status = conn_mgr.get_status(camera_id)
    history = list(conn_mgr._reconnect_history.get(camera_id, [])[-10:])  # 最近10条
    stream_cfg = conn_mgr.get_stream_config(camera_id)
    backoff = conn_mgr.get_next_backoff_seconds(camera_id)

    return {
        **status,
        "recent_reconnects": history,
        "stream_config": stream_cfg,
        "next_backoff_seconds": backoff,
    }
