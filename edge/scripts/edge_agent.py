#!/usr/bin/env python3
"""Jetson边缘盒子 agent — 报到 · 心跳 · 拉配置 · 自动推理

⚠️ DEPRECATED — 功能已合并至 edge/agent/server.py。
    edge/agent/server.py 统一了 kitchen + front-hall + edge_agent 三者的能力，
    单端口 9100，配置驱动模块激活。
    本文件保留作参考，不再使用。

部署：systemd 自启或手动运行
    python3 edge_agent.py --device-id jetson-yuhuan-01 --hub http://192.168.2.85:8098
"""

import argparse, json, os, subprocess, time, urllib.request
from pathlib import Path
from datetime import datetime

HUB_URL = os.environ.get("HOTPOT_HUB_URL", "http://192.168.2.85:8098")
DEVICE_ID = os.environ.get("HOTPOT_DEVICE_ID", "jetson-yuhuan-01")
STORE_ID = os.environ.get("HOTPOT_STORE_ID", "store_yuhuan")
CONFIG_FILE = Path("/opt/hotpot-infer/config/device_config.json")
BRIDGE_SCRIPT = Path("/opt/hotpot-infer/bridge_waste_vision.sh")
IPC_CONFIG = Path("/opt/hotpot-infer/config/ipc_config.yml")

# ─── Hub 通信 ───

def _post(url: str, data: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json", "X-Api-Key": "test-key"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())

def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"X-Api-Key": "test-key"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def register() -> dict:
    """向 Hub 报到，获取当前配置。"""
    return _post(f"{HUB_URL}/v1/devices/register", {
        "device_id": DEVICE_ID,
        "store_id": STORE_ID,
        "device_type": "jetson",
        "ip": "192.168.2.240",
        "hardware": {"model": "Orin 32GB", "jetpack": "5.0"},
    })


def pull_config() -> dict:
    """拉最新配置（RTSP流列表、推理参数）。"""
    return _get(f"{HUB_URL}/v1/devices/{DEVICE_ID}/config")


def heartbeat() -> dict:
    """心跳（复用 register 端点）。"""
    return _post(f"{HUB_URL}/v1/devices/register", {
        "device_id": DEVICE_ID,
        "store_id": STORE_ID,
        "device_type": "jetson",
        "ip": "192.168.2.240",
    })


# ─── 配置应用 ───

def apply_config(config: dict) -> bool:
    """将 Hub 下发的配置写入本地，写 IPC 配置文件。"""
    streams = config.get("rtsp_streams", [])
    if not streams:
        return False
    
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False))
    
    # 写 IPC 抓帧配置
    ipc_config = {"cameras": []}
    for s in streams:
        if s.get("enabled") and s.get("url"):
            ipc_config["cameras"].append({
                "zone": s["zone"],
                "url": s["url"],
                "camera_id": s.get("camera_id", "cam01"),
            })
    
    IPC_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    IPC_CONFIG.write_text(
        "\n".join(f"{c['zone']}: {c['url']}" for c in ipc_config["cameras"])
    )
    return True


# ─── 主循环 ───

def main():
    parser = argparse.ArgumentParser(description="Hotpot Edge Agent")
    parser.add_argument("--device-id", default=DEVICE_ID)
    parser.add_argument("--hub", default=HUB_URL)
    parser.add_argument("--heartbeat", type=int, default=30, help="心跳间隔(秒)")
    parser.add_argument("--config-interval", type=int, default=60, help="拉配置间隔(秒)")
    args = parser.parse_args()

    global DEVICE_ID, HUB_URL
    DEVICE_ID = args.device_id
    HUB_URL = args.hub

    print(f"[Agent] {DEVICE_ID} 启动, Hub={HUB_URL}")

    # ① 报到
    try:
        resp = register()
        print(f"[Agent] 报到成功: {resp.get('config', {}).get('rtsp_streams', [])}")
        apply_config(resp.get("config", {}))
    except Exception as e:
        print(f"[Agent] 报到失败: {e}, 30s 后重试")

    last_config_pull = 0

    while True:
        try:
            now = time.time()

            # ② 心跳
            hb = heartbeat()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 心跳 ok")

            # ③ 定期拉配置
            if now - last_config_pull > args.config_interval:
                cfg = pull_config()
                changed = apply_config(cfg.get("config", {}))
                if changed:
                    print(f"[Agent] 配置已更新: {cfg['config']['rtsp_streams']}")
                last_config_pull = now

            # ④ 如果配置中有RTSP流且抓帧脚本就绪，可以考虑触发一次推理
            # （后续集成 IPC grabber 时启用）

        except Exception as e:
            print(f"[Agent] 错误: {e}")

        time.sleep(args.heartbeat)


if __name__ == "__main__":
    main()
