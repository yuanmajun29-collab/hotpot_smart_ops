"""
系统资源 API
GET /api/v1/system/info          设备基本信息
GET /api/v1/system/resources     系统资源(CPU/内存/GPU/磁盘)
GET /api/v1/system/uptime        运行时间
GET /api/v1/system/version       版本信息
PUT    /api/v1/system/network       更新网络配置
POST   /api/v1/system/restart       重启网络服务
"""

import time
import platform
import psutil
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

# L2 PIN 认证依赖 (Step 5)
from middleware import get_current_session

router = APIRouter()

# ── 响应模型 ──

class DeviceInfo(BaseModel):
    device_id: str
    device_name: str
    store_name: str
    status: str
    uptime_seconds: int
    version: str
    ip_address: str
    mac_address: str
    initialized: bool
    hostname: str
    os_info: str
    python_version: str


class CpuInfo(BaseModel):
    percent: float
    cores: int
    freq_mhz: float
    temp_celsius: Optional[float] = None


class MemoryInfo(BaseModel):
    total_mb: float
    used_mb: float
    free_mb: float
    percent: float


class GpuInfo(BaseModel):
    model: Optional[str] = None
    utilization_pct: Optional[float] = None
    memory_used_mb: Optional[float] = None
    memory_total_mb: Optional[float] = None
    temperature_celsius: Optional[float] = None


class StorageInfo(BaseModel):
    total_gb: float
    used_gb: float
    free_gb: float
    percent: float


class SystemResources(BaseModel):
    cpu: CpuInfo
    memory: MemoryInfo
    gpu: GpuInfo
    storage: StorageInfo
    uptime_seconds: int
    load_average: list


# ── 辅助函数 ──

def _get_uptime() -> int:
    """获取系统运行时间(秒)"""
    return int(time.time() - psutil.boot_time())


def _get_ip_address() -> str:
    """获取主IP地址"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"


def _get_gpu_info() -> GpuInfo:
    """尝试获取GPU信息(Jetson)"""
    try:
        # 尝试读取 NVIDIA GPU 状态 (Jetson)
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(", ")
            return GpuInfo(
                model=parts[0].strip(),
                utilization_pct=float(parts[1].strip()),
                memory_used_mb=float(parts[2].strip()) / 1024,
                memory_total_mb=float(parts[3].strip()) / 1024,
                temperature_celsius=float(parts[4].strip()),
            )
    except:
        pass
    return GpuInfo()


def _get_cpu_temp() -> Optional[float]:
    """尝试获取CPU温度"""
    try:
        if hasattr(psutil, "sensors_temperatures"):
            temps = psutil.sensors_temperatures()
            for name, entries in temps.items():
                if entries:
                    return entries[0].current
    except:
        pass
    return None


# ── API 端点 ──

@router.get("/system/info", response_model=DeviceInfo)
async def get_device_info(_=Depends(get_current_session)):
    """设备基本信息"""
    # TODO: 从 conf/device.json 读取实际配置
    return DeviceInfo(
        device_id="edge-jiaojiang-001",
        device_name="椒江店-01号盒",
        store_name="冯校长火锅(椒江店)",
        status="online",
        uptime_seconds=_get_uptime(),
        version="1.1.0",
        ip_address=_get_ip_address(),
        mac_address="AA:BB:CC:DD:EE:FF",  # TODO: 实际获取
        initialized=True,
        hostname=platform.node(),
        os_info=f"{platform.system()} {platform.release()}",
        python_version=platform.python_version(),
    )


@router.get("/system/resources", response_model=SystemResources)
async def get_system_resources(_=Depends(get_current_session)):
    """系统资源(CPU/内存/GPU/磁盘)"""
    cpu_percent = psutil.cpu_percent(interval=0.5)
    cpu_freq = psutil.cpu_freq()
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    return SystemResources(
        cpu=CpuInfo(
            percent=round(cpu_percent, 1),
            cores=psutil.cpu_count(),
            freq_mhz=round(cpu_freq.current, 0) if cpu_freq else 0,
            temp_celsius=_get_cpu_temp(),
        ),
        memory=MemoryInfo(
            total_mb=round(mem.total / 1024 / 1024, 1),
            used_mb=round(mem.used / 1024 / 1024, 1),
            free_mb=round(mem.available / 1024 / 1024, 1),
            percent=round(mem.percent, 1),
        ),
        gpu=_get_gpu_info(),
        storage=StorageInfo(
            total_gb=round(disk.total / 1024 / 1024 / 1024, 1),
            used_gb=round(disk.used / 1024 / 1024 / 1024, 1),
            free_gb=round(disk.free / 1024 / 1024 / 1024, 1),
            percent=round(disk.percent, 1),
        ),
        uptime_seconds=_get_uptime(),
        load_average=list(psutil.getloadavg()),
    )


@router.get("/system/uptime")
async def get_uptime(_=Depends(get_current_session)):
    """运行时间"""
    return {"uptime_seconds": _get_uptime(), "boot_time": psutil.boot_time()}


@router.get("/system/version")
async def get_version(_=Depends(get_current_session)):
    """版本信息"""
    return {
        "version": "1.1.0",
        "build_date": "2026-08-01",
        "git_commit": "dev",  # TODO: 实际获取
        "dependencies": {
            "fastapi": "0.x",
            "uvicorn": "0.x",
            "psutil": "5.x",
        }
    }


@router.put("/system/network")
async def update_network_config(config: dict, _=Depends(get_current_session)):
    """
    更新网络配置
    注意: 此操作需要root权限，且会断开当前连接
    """
    # MVP阶段仅记录日志，不实际执行
    # 生产环境需调用 nmcli / netplan / network-manager
    print(f"[System API] 网络配置更新请求(未执行): {config}")
    return {"code": 0, "message": "网络配置已保存，将在重启后生效"}


@router.post("/system/restart")
async def restart_network_service(_=Depends(get_current_session)):
    """重启网络服务 (危险操作，需二次确认)"""
    # MVP阶段仅模拟
    return {"code": 0, "message": "系统将在5秒后重启网络服务"}
