#!/usr/bin/env python3
"""
Train / export table-state YOLO classifier (DEV-202).

Requires: pip install ultralytics

Example:
  python3 scripts/build_table_dataset.py --store-id store_yuhuan --auto-label mock
  python3 scripts/train_table_classifier.py --epochs 30
  cp runs/classify/table_v1/weights/best.onnx models/table_state.onnx
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET = PROJECT_ROOT / "datasets" / "table_state"
MODELS_DIR = PROJECT_ROOT / "models"


def main() -> None:
    parser = argparse.ArgumentParser(description="Train YOLO table-state classifier")
    parser.add_argument("--data", default=str(DATASET))
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--imgsz", type=int, default=224)
    parser.add_argument("--model", default="yolov8n-cls.pt")
    parser.add_argument("--export-onnx", action="store_true")
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.is_dir():
        print(f"[ERROR] Dataset not found: {data_path}")
        print("Run: python3 scripts/build_table_dataset.py --auto-label mock")
        sys.exit(1)

    try:
        from ultralytics import YOLO
    except ImportError:
        print("[ERROR] ultralytics not installed. Run: pip install ultralytics")
        sys.exit(1)

    yolo = YOLO(args.model)
    results = yolo.train(
        data=str(data_path),
        epochs=args.epochs,
        imgsz=args.imgsz,
        project=str(PROJECT_ROOT / "runs" / "classify"),
        name="table_v1",
        exist_ok=True,
    )
    best_pt = Path(results.save_dir) / "weights" / "best.pt"
    print(f"[OK] Training complete: {best_pt}")

    if args.export_onnx:
        export_model = YOLO(str(best_pt))
        export_path = export_model.export(format="onnx", imgsz=args.imgsz)
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        dest = MODELS_DIR / "table_state.onnx"
        shutil.copy(export_path, dest)
        print(f"[OK] ONNX exported to {dest}")


if __name__ == "__main__":
    main()
