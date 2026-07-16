#!/usr/bin/env python3
"""边缘 agent 统一入口 — 注册 · 心跳 · 配置轮询 · 模块激活

替代 edge/kitchen/server.py + edge/front_hall/server.py + edge/scripts/edge_agent.py。
单端口 9100，配置驱动按模块激活后厨/前厅推理。

启动: PYTHONPATH=. python3 -m edge.agent.server
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from edge.agent.config import (
    HUB_URL, DEVICE_ID, STORE_ID, API_KEY,
    SERVER_PORT, SERVER_HOST,
    HEARTBEAT_INTERVAL, CONFIG_POLL_INTERVAL,
    IPC_CONFIG_PATH, DEVICE_CONFIG_PATH,
)
from edge.agent.modules import kitchen_infer, front_hall_infer
from edge.agent.buffer import InferenceBuffer

# ─── 日志 ───
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("edge-agent")

# ─── FastAPI 应用 ───
app = FastAPI(title="Hotpot Edge Agent", version="2.0")

# 边缘设备不需要 CORS

# ─── 全局状态 ───
_device_config: Dict[str, Any] = {}
_active_modules: List[str] = []
_last_config_hash: str = ""

# ─── 推断缓冲层（离线缓冲 + 自动重试）───
_buffer: InferenceBuffer = InferenceBuffer(
    db_path=os.environ.get("HOTPOT_BUFFER_DIR", "/tmp/hotpot_buffer") + "/inference.db",
    hub_url=HUB_URL,
    api_key=API_KEY,
)

# ─── 模块注册表（替代硬编码激活）───
_MODULE_REGISTRY: Dict[str, Any] = {
    "kitchen": kitchen_infer,
    "front_hall": front_hall_infer,
    "receiving": None,  # receiving module uses its own MQTT/detector processes
}
# 新场景只需在此注册表加一行即可自动激活

# ─── Hub 通信 ───

_hub_client: httpx.AsyncClient = None


async def _get_hub_client() -> httpx.AsyncClient:
    """复用连接池，避免每次创建新 AsyncClient。"""
    global _hub_client
    if _hub_client is None or _hub_client.is_closed:
        _hub_client = httpx.AsyncClient(
            timeout=httpx.Timeout(10),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )
    return _hub_client


async def _hub_post(path: str, data: dict) -> dict:
    """向 Hub POST，带 X-Api-Key。"""
    client = await _get_hub_client()
    resp = await client.post(
        f"{HUB_URL}{path}",
        json=data,
        headers={"Content-Type": "application/json", "X-Api-Key": API_KEY},
    )
    resp.raise_for_status()
    return resp.json()


async def register() -> dict:
    """设备向 Hub 注册，上报当前激活模块。"""
    return await _hub_post("/api/v1/devices/register", {
        "device_id": DEVICE_ID,
        "store_id": STORE_ID,
        "ip": _get_local_ip(),
        "device_type": "jetson",
        "hardware": {"model": "Orin", "jetpack": "5.0"},
        "active_modules": _active_modules,
    })


async def heartbeat() -> dict:
    """设备心跳续期，上报状态。"""
    return await _hub_post(f"/api/v1/devices/{DEVICE_ID}/heartbeat", {
        "device_id": DEVICE_ID,
        "active_modules": _active_modules,
        "inference_count": 0,
        "metrics": {"ip": _get_local_ip()},
    })


async def pull_config() -> dict:
    """设备级配置拉取：从 Hub 拉模块配置。"""
    return await _hub_post(f"/api/v1/devices/{DEVICE_ID}/pull-config", {})


def _get_local_ip() -> str:
    """获取本地 IP。"""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.168.2.85", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ─── 配置应用 ───

def _config_hash(config: dict) -> str:
    """配置摘要 hash，用于变更检测（模块名+启用状态+camera数量）。"""
    modules = config.get("modules", {})
    sig = sorted(
        (name, m.get("enabled", False), len(m.get("cameras", [])))
        for name, m in modules.items()
    )
    return json.dumps(sig, sort_keys=True)


def _extract_active_modules(config: dict) -> List[str]:
    """从 module 配置提取已启用的模块名列表。"""
    modules = config.get("modules", {})
    return sorted(name for name, m in modules.items() if m.get("enabled"))


def _write_ipc_config(config: dict) -> None:
    """将模块配置中所有 camera 写入 IPC 配置文件。DEV_MODE 下跳过。"""
    if os.environ.get("HOTPOT_DEV_MODE"):
        return
    modules = config.get("modules", {})
    Path(IPC_CONFIG_PATH).parent.mkdir(parents=True, exist_ok=True)

    lines = []
    for mod_name, mod in modules.items():
        if mod.get("enabled"):
            for cam in mod.get("cameras", []):
                lines.append(f"{mod_name}: {cam}")

    Path(IPC_CONFIG_PATH).write_text("\n".join(lines))


def _save_device_config(config: dict) -> None:
    """持久化设备配置到本地。DEV_MODE 下跳过文件写入。"""
    if os.environ.get("HOTPOT_DEV_MODE"):
        logger.info("DEV_MODE: 跳过设备配置持久化")
        return
    Path(DEVICE_CONFIG_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(DEVICE_CONFIG_PATH).write_text(json.dumps(config, indent=2, ensure_ascii=False))


def apply_device_config(config: dict) -> bool:
    """应用模块化配置：按 enabled 启停模块、写 IPC 配置。

    平台推送 → Hub → 设备直拉 → 本地应用。
    Returns: True 表示模块列表有变化。
    """
    global _active_modules, _last_config_hash, _device_config

    if not config or not config.get("modules"):
        logger.info("无有效模块配置，跳过")
        return False

    new_hash = _config_hash(config)
    new_modules = _extract_active_modules(config)

    changed = (new_hash != _last_config_hash)

    if changed:
        logger.info(f"模块变更: {_active_modules} → {new_modules}")

        # 按注册表激活/停用模块
        for mod_name, mod in _MODULE_REGISTRY.items():
            mod._active = mod_name in new_modules

        _active_modules = new_modules
        _last_config_hash = new_hash

        for mod_name in new_modules:
            logger.info(f"✓ {mod_name} 模块已激活")
        for mod_name in _MODULE_REGISTRY:
            if mod_name not in new_modules:
                logger.info(f"✗ {mod_name} 模块已停用")

    # 始终写 IPC 配置和设备配置
    _write_ipc_config(config)
    _save_device_config(config)
    _device_config = config

    return changed


# ─── 后台协程 ───

async def heartbeat_loop():
    """心跳协程：每 HEARTBEAT_INTERVAL 秒向 Hub 报到续期 + 接收待下发配置。"""
    while True:
        try:
            hb = await heartbeat()
            config = hb.get("config")
            if config:
                logger.info("心跳返回待下发配置")
                apply_device_config(config)
        except Exception as e:
            logger.warning(f"心跳失败: {e}")
        await asyncio.sleep(HEARTBEAT_INTERVAL)


async def config_poll_loop():
    """配置轮询协程：每 CONFIG_POLL_INTERVAL 秒设备级拉配置并热重载。"""
    # 首次等 5s，确保 register 先完成
    await asyncio.sleep(5)

    while True:
        try:
            resp = await pull_config()
            config = resp.get("config")
            if config:
                changed = apply_device_config(config)
                if changed:
                    logger.info("配置已热重载")
        except Exception as e:
            logger.warning(f"配置轮询失败: {e}")
        await asyncio.sleep(CONFIG_POLL_INTERVAL)


# ─── 端点 ───

@app.get("/health")
def health():
    """总体健康 + 模块状态。"""
    return {
        "status": "ok",
        "service": "edge-agent",
        "device_id": DEVICE_ID,
        "store_id": STORE_ID,
        "hub": HUB_URL,
        "modules": {
            "kitchen": {
                "active": kitchen_infer._active,
                "zone": kitchen_infer._zone,
            },
            "front_hall": {
                "active": front_hall_infer._active,
            },
        },
        "active_modules": _active_modules,
        "port": SERVER_PORT,
    }


@app.get("/debug/engine")
def debug_engine():
    """诊断端点：验证引擎导入和 YOLO 加载状态。"""
    import cv2
    from pathlib import Path
    from edge.front_hall.inference.engines import get_engine
    from edge.common.detector.real_yolo import RealYoloDetector

    project_root = Path(__file__).resolve().parents[2]
    test_img = cv2.imread(str(project_root / "demo" / "data" / "bus.jpg"))

    info = {
        "python_path": __import__("sys").path[:3],
        "edge_pkg": __import__("edge").__file__,
        "yolo_module": RealYoloDetector.__module__,
    }

    try:
        yolo = get_engine("yolo")
        info["engine_type"] = type(yolo).__name__
        result = yolo.detect(test_img, zone="front")
        info["detections"] = result["total_detections"]
        info["labels"] = result.get("label_counts", {})
    except Exception as e:
        info["error"] = str(e)

    return info


@app.get("/buffer/stats")
async def buffer_stats():
    """推断缓冲状态：队列长度、发送统计等。"""
    return await _buffer.stats()


# ─── 注册路由 ───
app.include_router(kitchen_infer.router)
app.include_router(front_hall_infer.router)

# 挂载 /output 静态目录
front_hall_infer.mount_static(app)


# ─── 启动事件 ───

@app.on_event("startup")
async def startup():
    """启动：注册 → 拿配置 → 激活模块 → 起后台协程。"""
    logger.info(f"Edge Agent 启动 — device={DEVICE_ID}, store={STORE_ID}, hub={HUB_URL}")

    # ① 启动推断缓冲层
    await _buffer.start()
    # 暴露给模块使用
    kitchen_infer.buffer = _buffer
    front_hall_infer.buffer = _buffer

    # ② 注册到 Hub
    try:
        resp = await register()
        config = resp.get("config")
        if config:
            logger.info(f"注册成功，获取到模块配置: {list(config.get('modules', {}).keys())}")
            apply_device_config(config)
        else:
            logger.info("注册成功，无已有配置（等待平台推送）")
    except Exception as e:
        logger.error(f"注册失败，将以无配置模式运行: {e}")

    # DEV_MODE 兜底：自动激活所有模块以便本地调试
    if os.environ.get("HOTPOT_DEV_MODE") and not _active_modules:
        default_cfg = {
            "modules": {
                "kitchen": {"enabled": False, "cameras": [], "inference_interval": 30},
                "front_hall": {"enabled": True, "cameras": [], "inference_interval": 30},
            }
        }
        logger.info("DEV_MODE: 自动激活 front_hall 模块（kitchen 保持关闭）")
        apply_device_config(default_cfg)

    # ③ 启动后台协程
    asyncio.create_task(heartbeat_loop())
    asyncio.create_task(config_poll_loop())

    logger.info(f"Edge Agent 就绪 — 端口 {SERVER_PORT}, buffer 已启用")


# ─── 主入口 ───

def main():
    uvicorn.run(
        "server:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
