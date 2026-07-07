#!/usr/bin/env python3
"""
RKNN deployment helper for hotpot edge detection.

Wraps Detect_Inference_Project ONNX->RKNN conversion workflow.
Run on host with rknn-toolkit2 installed; on device use DETECT_rknn3566.py.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

DETECT_PROJECT = Path("/home/liuwz/Detect_Inference_Project")
HOTPOT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = HOTPOT_ROOT / "edge" / "rknn_deploy" / "output"


def check_detect_project() -> bool:
    required = [
        DETECT_PROJECT / "DETECT_rknn3566.py",
        DETECT_PROJECT / "DETECT_onnx.py",
    ]
    missing = [p for p in required if not p.exists()]
    if missing:
        print("[ERROR] Detect_Inference_Project not found or incomplete:")
        for p in missing:
            print(f"  - {p}")
        return False
    return True


def export_instructions(onnx_path: Path, target: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    readme = OUTPUT_DIR / "DEPLOY_README.txt"
    readme.write_text(
        f"""Hotpot Edge RKNN Deployment Guide
===================================

ONNX model: {onnx_path}
Target SoC: {target}

Steps (on development machine with rknn-toolkit2):
1. cd {DETECT_PROJECT}
2. Convert ONNX to RKNN using project scripts (see DETECT_rknn.py / DETECT_rknn3566.py)
3. Copy .rknn file to edge device: {OUTPUT_DIR}/

Steps (on RK3566/RK3588 edge device):
1. Install rknn-lite / rknpu runtime
2. python {DETECT_PROJECT}/DETECT_rknn3566.py --model {OUTPUT_DIR}/hotpot_detect.rknn
3. Integrate with hotpot_detector.py via --backend onnx (future) or sidecar HTTP

PoC note: mock backend runs without RKNN hardware for demo.
""",
        encoding="utf-8",
    )
    print(f"[INFO] Deploy guide written to {readme}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Hotpot RKNN deploy helper")
    parser.add_argument(
        "--onnx",
        default=str(DETECT_PROJECT / "MODEL" / "detect.onnx"),
        help="Path to ONNX detection model",
    )
    parser.add_argument("--target", choices=("rk3566", "rk3588"), default="rk3566")
    parser.add_argument("--copy-scripts", action="store_true", help="Copy RKNN scripts to output dir")
    args = parser.parse_args()

    if not check_detect_project():
        sys.exit(1)

    onnx_path = Path(args.onnx)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.copy_scripts:
        for name in ("DETECT_rknn3566.py", "DETECT_rknn.py", "POST_decoder.py", "POST_function.py"):
            src = DETECT_PROJECT / name
            if src.exists():
                shutil.copy2(src, OUTPUT_DIR / name)
                print(f"[INFO] Copied {name}")

    export_instructions(onnx_path, args.target)
    print("[INFO] RKNN deploy prep complete. Train/export hotpot-specific weights separately.")


if __name__ == "__main__":
    main()
