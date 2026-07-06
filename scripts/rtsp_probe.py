#!/usr/bin/env python3
"""Probe RTSP stream connectivity for pilot stores (DEV-203)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from common.store_config import DEFAULT_UAT_ROOT, load_store_config


def probe_rtsp(url: str, timeout_sec: float = 8.0) -> dict:
    os.environ["HOTPOT_RTSP_ENABLED"] = "1"
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    start = time.time()
    ok = False
    frame_shape = None
    error = ""
    while time.time() - start < timeout_sec:
        if cap.isOpened():
            ret, frame = cap.read()
            if ret and frame is not None:
                ok = True
                frame_shape = list(frame.shape)
                break
        time.sleep(0.3)
    if not ok:
        error = "no frame within timeout"
    cap.release()
    return {
        "url": url,
        "ok": ok,
        "frame_shape": frame_shape,
        "latency_ms": int((time.time() - start) * 1000),
        "error": error,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="RTSP connectivity probe")
    parser.add_argument("--store-id", default="store_yuhuan")
    parser.add_argument("--uat-root", default=str(DEFAULT_UAT_ROOT))
    parser.add_argument("--url", default="", help="Direct RTSP URL override")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    results = []
    if args.url:
        results.append(probe_rtsp(args.url))
    else:
        config = load_store_config(args.store_id, Path(args.uat_root))
        for cam in config.get("cameras", []):
            rtsp = cam.get("rtsp", "")
            if not rtsp:
                continue
            r = probe_rtsp(rtsp)
            r["camera_id"] = cam.get("id")
            r["zone"] = cam.get("zone")
            results.append(r)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for r in results:
            status = "OK" if r["ok"] else "FAIL"
            print(f"[{status}] {r.get('camera_id', r['url'])} shape={r.get('frame_shape')} {r.get('error', '')}")

    sys.exit(0 if all(r["ok"] for r in results) else 1 if results else 0)


if __name__ == "__main__":
    main()
