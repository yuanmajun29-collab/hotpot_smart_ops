#!/usr/bin/env python3
"""
IPC Frame Grabber — 从 RTSP/RTMP 摄像头拉流抽帧，保存到本地，供 VLM 桥调用。

用法:
    python3 /root/ipc_frame_grabber.py                          # 按配置文件抽帧
    python3 /root/ipc_frame_grabber.py --url rtsp://x.x.x.x    # 临时指定流地址
    python3 /root/ipc_frame_grabber.py --once                   # 单次抽帧
    python3 /root/ipc_frame_grabber.py --interval 5             # 每5秒抽一帧（覆盖配置）

配置: /root/ipc_config.yml
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2

# ── 默认配置 ──────────────────────────────────────────────────────────────
CFG_PATH = "/root/ipc_config.yml"
FRAME_DIR = "/tmp/ipc_frames"
INFERENCE_SCRIPT = "/root/bridge_waste_vision.sh"

# 默认 IPC 参数（可在 ipc_config.yml 中覆盖）
DEFAULT_CONFIG = {
    "stream_url": "rtsp://admin:password@192.168.1.64:554/Streaming/Channels/101",
    "interval_seconds": 10,      # 抽帧间隔（秒）
    "save_latest_only": True,    # 仅保留最新一帧
    "skip_if_stale": True,       # 跳过超时流
    "stream_timeout": 10,        # 流连接超时（秒）
    "auto_infer": False,         # 抽帧后是否自动触发推理
    "hub_url": "http://192.168.2.85:8098",
    "store_id": "store_yuhuan",
    "zone": "备餐废弃区",
    "infer_on_frame_count": 1,   # 每 N 帧触发一次推理（仅在 auto_infer=true 时有效）
}


def load_config(path: str = CFG_PATH) -> dict:
    """加载 YAML 配置，回退到默认值。"""
    config = DEFAULT_CONFIG.copy()

    if not os.path.exists(path):
        print(f"[grabber] 配置文件不存在: {path}，使用默认配置")
        return config

    try:
        import yaml
        with open(path) as f:
            user_config = yaml.safe_load(f)
        if user_config:
            config.update(user_config)
    except ImportError:
        # 无 PyYAML，尝试简易 JSON 格式
        try:
            with open(path) as f:
                user_config = json.load(f)
            if user_config:
                config.update(user_config)
        except Exception:
            print(f"[grabber] 无法解析配置文件 {path}，使用默认配置")

    return config


def connect_stream(url: str, timeout: int = 10) -> cv2.VideoCapture | None:
    """连接 RTSP/RTMP 流。"""
    # 尝试多种后端
    backends = [
        (cv2.CAP_FFMPEG, f"FFMPEG → {url}"),
        (cv2.CAP_GSTREAMER, f"GSTREAMER → {url}"),
    ]

    # GStreamer pipeline (Jetson 硬件加速)
    gst_pipeline = (
        f"rtspsrc location={url} latency=2000 ! "
        f"rtph264depay ! h264parse ! nvv4l2decoder ! "
        f"nvvidconv ! video/x-raw,format=BGRx ! "
        f"videoconvert ! video/x-raw,format=BGR ! appsink"
    )

    for backend, label in backends:
        try:
            if backend == cv2.CAP_GSTREAMER:
                cap = cv2.VideoCapture(gst_pipeline, cv2.CAP_GSTREAMER)
            else:
                cap = cv2.VideoCapture(url, backend)

            if cap.isOpened():
                # 验证能读到帧
                ret, frame = cap.read()
                if ret and frame is not None:
                    print(f"[grabber] ✅ 流连接成功: {label}")
                    return cap
                cap.release()
            else:
                cap.release()
        except Exception as e:
            print(f"[grabber] ⚠️ {label} 失败: {e}")

    print(f"[grabber] ❌ 所有后端连接失败: {url}")
    return None


def grab_frame(cap: cv2.VideoCapture, save_dir: str, save_latest_only: bool = True) -> str | None:
    """从已连接的流中抽取一帧，保存为 JPEG。返回文件路径或 None。"""
    ret, frame = cap.read()
    if not ret or frame is None:
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"ipc_{timestamp}.jpg"

    if save_latest_only:
        # 固定文件名，覆盖旧帧
        filepath = os.path.join(save_dir, "ipc_latest.jpg")
    else:
        filepath = os.path.join(save_dir, filename)

    os.makedirs(save_dir, exist_ok=True)
    cv2.imwrite(filepath, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return filepath


def run_inference(image_path: str, config: dict):
    """调用 VLM 桥进行推理。"""
    import subprocess

    hub_url = config.get("hub_url", DEFAULT_CONFIG["hub_url"])
    store_id = config.get("store_id", DEFAULT_CONFIG["store_id"])
    zone = config.get("zone", DEFAULT_CONFIG["zone"])

    env = os.environ.copy()
    env["HOTPOT_HUB_URL"] = hub_url
    env["HOTPOT_STORE_ID"] = store_id

    cmd = ["bash", INFERENCE_SCRIPT, image_path, zone, hub_url]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        if result.returncode != 0:
            print(f"[grabber] 推理失败: {result.stderr.strip()[:200]}")
        else:
            # 提取关键行
            for line in result.stdout.strip().split("\n"):
                if "Hub response" in line or "Parsed" in line or "VLM raw" in line:
                    print(f"[grabber]   {line.strip()}")
    except subprocess.TimeoutExpired:
        print("[grabber] 推理超时 (120s)")
    except Exception as e:
        print(f"[grabber] 推理异常: {e}")


def run_continuous(config: dict):
    """持续抽帧循环。"""
    url = config["stream_url"]
    interval = config["interval_seconds"]
    save_latest = config["save_latest_only"]
    timeout = config["stream_timeout"]
    auto_infer = config["auto_infer"]
    infer_every = config.get("infer_on_frame_count", 1)

    os.makedirs(FRAME_DIR, exist_ok=True)

    cap = connect_stream(url, timeout)
    if cap is None:
        print("[grabber] 无法连接流，退出")
        sys.exit(1)

    frame_count = 0
    print(f"[grabber] 🎥 开始抽帧，间隔 {interval}s，保存到 {FRAME_DIR}/")
    print(f"[grabber]    自动推理: {'✅' if auto_infer else '❌'}")

    try:
        while True:
            filepath = grab_frame(cap, FRAME_DIR, save_latest)
            frame_count += 1

            if filepath:
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"[grabber] [{ts}] 第{frame_count}帧 → {filepath}")

                if auto_infer and frame_count % infer_every == 0:
                    print(f"[grabber] 🔍 触发推理...")
                    run_inference(filepath, config)

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n[grabber] 收到中断信号，清理中...")
    finally:
        cap.release()
        print("[grabber] 流已释放，退出")


def run_once(config: dict):
    """单次抽帧（用于测试）。"""
    url = config["stream_url"]
    timeout = config["stream_timeout"]
    auto_infer = config.get("auto_infer", True)

    os.makedirs(FRAME_DIR, exist_ok=True)

    cap = connect_stream(url, timeout)
    if cap is None:
        print("[grabber] 无法连接流")
        sys.exit(1)

    filepath = grab_frame(cap, FRAME_DIR, save_latest_only=False)
    cap.release()

    if filepath:
        print(f"[grabber] ✅ 单帧保存: {filepath}")

        if auto_infer:
            run_inference(filepath, config)
    else:
        print("[grabber] ❌ 抽帧失败")
        sys.exit(1)


# ── CLI ──────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="IPC Frame Grabber for Jetson VLM Pipeline")
    parser.add_argument("--url", help="IPC 流地址 (rtsp:// 或 rtmp://)")
    parser.add_argument("--once", action="store_true", help="单次抽帧后退出")
    parser.add_argument("--interval", type=int, help="抽帧间隔（秒）")
    parser.add_argument("--no-infer", action="store_true", help="不触发推理")
    parser.add_argument("--config", default=CFG_PATH, help=f"配置文件路径 (默认: {CFG_PATH})")
    args = parser.parse_args()

    config = load_config(args.config)

    # CLI 参数覆盖
    if args.url:
        config["stream_url"] = args.url
    if args.interval:
        config["interval_seconds"] = args.interval
    if args.no_infer:
        config["auto_infer"] = False

    print(f"[grabber] 配置加载完成")
    print(f"[grabber]   流地址: {config['stream_url']}")
    print(f"[grabber]   间隔: {config['interval_seconds']}s")
    print(f"[grabber]   推理: {'启用' if config['auto_infer'] else '禁用'}")
    print()

    if args.once:
        # 单次模式强制开启推理（除非显式 --no-infer）
        if not args.no_infer:
            config["auto_infer"] = True
        run_once(config)
    else:
        run_continuous(config)


if __name__ == "__main__":
    main()
