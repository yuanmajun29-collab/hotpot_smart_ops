#!/usr/bin/env python3
"""Switch pilot store CV config between demo (file/mock) and pilot (RTSP/yolo) — BL-01."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.store_config import DEFAULT_UAT_ROOT, uat_dir

PILOT_STORES = ("store_yuhuan", "store_jiaojiang")
BACKENDS = ("mock", "yolo", "rknn", "onnx")


def load_config(store_id: str, uat_root: Path) -> Dict[str, Any]:
    path = uat_dir(store_id, uat_root) / "config.json"
    return json.loads(path.read_text(encoding="utf-8"))


def save_config(store_id: str, config: Dict[str, Any], uat_root: Path) -> Path:
    path = uat_dir(store_id, uat_root) / "config.json"
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def apply_mode(
    config: Dict[str, Any],
    *,
    mode: str,
    backend: str,
) -> Dict[str, Any]:
    config = dict(config)
    stream_mode = "rtsp" if mode == "pilot" else "file"
    cameras: List[Dict[str, Any]] = []
    for cam in config.get("cameras", []):
        cam = dict(cam)
        cam["stream_mode"] = stream_mode
        cameras.append(cam)
    config["cameras"] = cameras
    if mode == "pilot":
        config["model_version"] = f"table_v1.0.0-{backend}"
        config["cv_backend"] = backend
        config["phase"] = "Phase1-Pilot-CV"
    else:
        config["model_version"] = "table_v1.0.0-mock"
        config.pop("cv_backend", None)
        config["phase"] = "Phase1-UAT"
    return config


def env_exports(mode: str, backend: str, hub_url: str) -> str:
    lines = [
        f"export HOTPOT_RTSP_ENABLED={'1' if mode == 'pilot' else '0'}",
        f"export HOTPOT_DETECTOR_BACKEND={backend}",
        f"export HOTPOT_UAT_ROOT={DEFAULT_UAT_ROOT}",
        f"export HOTPOT_HUB_URL={hub_url}",
        f"export VISION_BACKEND={backend}",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Enable/disable pilot CV (RTSP + yolo/rknn)")
    parser.add_argument(
        "--mode",
        choices=("demo", "pilot"),
        default="pilot",
        help="demo=file+mock, pilot=rtsp+backend",
    )
    parser.add_argument(
        "--backend",
        choices=BACKENDS,
        default="yolo",
        help="Detector backend when mode=pilot",
    )
    parser.add_argument("--store-id", action="append", help="Store id (repeatable); default both pilots")
    parser.add_argument("--uat-root", default=str(DEFAULT_UAT_ROOT))
    parser.add_argument("--hub-url", default="http://127.0.0.1:8088")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--print-env", action="store_true", help="Print export lines for shell")
    args = parser.parse_args()

    uat_root = Path(args.uat_root)
    store_ids = args.store_id or list(PILOT_STORES)
    backend = args.backend if args.mode == "pilot" else "mock"

    for sid in store_ids:
        config = load_config(sid, uat_root)
        updated = apply_mode(config, mode=args.mode, backend=backend)
        if args.dry_run:
            print(f"[dry-run] {sid}: stream_mode={updated['cameras'][0].get('stream_mode')}")
            continue
        path = save_config(sid, updated, uat_root)
        print(f"[OK] {sid} -> {path} ({args.mode}, backend={backend})")

    if args.print_env or not args.dry_run:
        print("\n# 环境变量（启动 vision worker 前执行）")
        print(env_exports(args.mode, backend, args.hub_url))
        print("\n# 重启 vision daemon 示例")
        print(
            f"VISION_BACKEND={backend} HOTPOT_RTSP_ENABLED={'1' if args.mode == 'pilot' else '0'} "
            f"./demo/run_vision_daemon.sh {args.hub_url}"
        )


if __name__ == "__main__":
    main()
