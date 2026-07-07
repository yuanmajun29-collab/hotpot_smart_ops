#!/usr/bin/env python3
"""边缘 agent 统一入口 — 注册 · 心跳 · 配置轮询 · 模块激活

替代 edge/kitchen/server.py + edge/front_hall/server.py + edge/scripts/edge_agent.py。
单端口 9100，配置驱动按 zone 激活后厨/前厅推理模块。

启动: python3 edge/agent/server.py  或  python3 -m edge.agent.server
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# 确保项目根目录在 sys.path（放末尾，避免遮蔽 stdlib platform 模块）
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.append(str(_PROJECT_ROOT))

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from edge.agent.config import (
    HUB_URL, GATEWAY_ID, DEVICE_ID, STORE_ID, API_KEY,
    SERVER_PORT, SERVER_HOST,
    HEARTBEAT_INTERVAL, CONFIG_POLL_INTERVAL,
    IPC_CONFIG_PATH, DEVICE_CONFIG_PATH,
)
from edge.agent.modules import kitchen_infer, front_hall_infer

# ─── 日志 ───
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("edge-agent")

# ─── FastAPI 应用 ───
app = FastAPI(title="Hotpot Edge Agent", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 全局状态 ───
_device_config: Dict[str, Any] = {}
_active_zones: List[str] = []
_last_config_hash: str = ""

# ─── Hub 通信 ───

async def _hub_post(path: str, data: dict) -> dict:
    """向 Hub POST，带 X-Api-Key。"""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{HUB_URL}{path}",
            json=data,
            headers={"Content-Type": "application/json", "X-Api-Key": API_KEY},
        )
        resp.raise_for_status()
        return resp.json()


async def _hub_get(path: str) -> dict:
    """向 Hub GET，带 X-Api-Key。"""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{HUB_URL}{path}",
            headers={"X-Api-Key": API_KEY},
        )
        resp.raise_for_status()
        return resp.json()


def _build_box_list() -> list:
    """构建当前网关所挂盒子列表。未来可从本地注册表/auto-discovery 组装。"""
    return [{
        "box_id": DEVICE_ID,
        "device_type": "jetson",
        "ip": "192.168.2.240",
        "active_zones": _active_zones,
        "status": "online",
    }]


async def register() -> dict:
    """网关向 Hub 报到，携所挂盒子列表。"""
    return await _hub_post("/v1/gateways/register", {
        "gateway_id": GATEWAY_ID,
        "store_id": STORE_ID,
        "ip": "192.168.2.240",
        "hardware": {"model": "Orin", "jetpack": "5.0"},
        "boxes": _build_box_list(),
    })


async def heartbeat() -> dict:
    """网关心跳续期，上报盒子当前状态。"""
    return await _hub_post(f"/v1/gateways/{GATEWAY_ID}/heartbeat", {
        "gateway_id": GATEWAY_ID,
        "boxes": _build_box_list(),
    })


async def pull_config() -> dict:
    """拉最新配置。"""
    return await _hub_get(f"/v1/devices/{DEVICE_ID}/config")


# ─── 配置应用 ───

def _config_hash(config: dict) -> str:
    """配置摘要 hash，用于变更检测。"""
    streams = config.get("rtsp_streams", [])
    zones = sorted({s.get("zone", "unknown") for s in streams})
    return json.dumps(zones, sort_keys=True)


def _extract_zones(config: dict) -> List[str]:
    """从 rtsp_streams 提取唯一 zone 列表。"""
    streams = config.get("rtsp_streams", [])
    return sorted({s["zone"] for s in streams if s.get("zone")})


def _write_ipc_config(config: dict) -> None:
    """将 RTSP 流配置写入 IPC 配置文件。"""
    streams = config.get("rtsp_streams", [])
    Path(IPC_CONFIG_PATH).parent.mkdir(parents=True, exist_ok=True)

    lines = []
    for s in streams:
        if s.get("enabled") and s.get("url"):
            lines.append(f"{s['zone']}: {s['url']}")

    Path(IPC_CONFIG_PATH).write_text("\n".join(lines))


def _save_device_config(config: dict) -> None:
    """持久化设备配置到本地。"""
    Path(DEVICE_CONFIG_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(DEVICE_CONFIG_PATH).write_text(json.dumps(config, indent=2, ensure_ascii=False))


def apply_config(config: dict) -> bool:
    """应用配置：写 IPC 配置、按 zone 激活/停用模块。

    Returns: True 表示 zone 列表有变化（触发了模块启停）。
    """
    global _active_zones, _last_config_hash, _device_config

    new_hash = _config_hash(config)
    new_zones = _extract_zones(config)

    zone_changed = (new_hash != _last_config_hash)

    if zone_changed:
        logger.info(f"配置变更: zones {_active_zones} → {new_zones}")

        # 按 zone 激活/停用模块
        kitchen_infer._active = "kitchen" in new_zones
        front_hall_infer._active = "front_hall" in new_zones

        _active_zones = new_zones
        _last_config_hash = new_hash

        if kitchen_infer._active:
            kitchen_infer._zone = "kitchen"
            logger.info("✓ kitchen 模块已激活")
        else:
            logger.info("✗ kitchen 模块已停用")

        if front_hall_infer._active:
            logger.info("✓ front-hall 模块已激活")
        else:
            logger.info("✗ front-hall 模块已停用")

    # 始终写 IPC 配置和设备配置
    _write_ipc_config(config)
    _save_device_config(config)
    _device_config = config

    return zone_changed


# ─── 后台协程 ───

async def heartbeat_loop():
    """心跳协程：每 HEARTBEAT_INTERVAL 秒向 Hub 报到续期。"""
    while True:
        try:
            hb = await heartbeat()
            logger.debug(f"心跳 ok")
        except Exception as e:
            logger.warning(f"心跳失败: {e}")
        await asyncio.sleep(HEARTBEAT_INTERVAL)


async def config_poll_loop():
    """配置轮询协程：每 CONFIG_POLL_INTERVAL 秒拉配置并热重载。"""
    # 首次等 5s，确保 register 先完成
    await asyncio.sleep(5)

    while True:
        try:
            resp = await pull_config()
            cfg = resp.get("config", resp)
            changed = apply_config(cfg)
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
        "active_zones": _active_zones,
        "port": SERVER_PORT,
    }


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

    # ① 注册到 Hub
    try:
        resp = await register()
        config = resp.get("config", {})
        logger.info(f"注册成功，获取到配置: {json.dumps(config, ensure_ascii=False)[:200]}")
        apply_config(config)
    except Exception as e:
        logger.error(f"注册失败，将以无配置模式运行: {e}")

    # ② 启动后台协程
    asyncio.create_task(heartbeat_loop())
    asyncio.create_task(config_poll_loop())

    logger.info(f"Edge Agent 就绪 — 端口 {SERVER_PORT}")


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
