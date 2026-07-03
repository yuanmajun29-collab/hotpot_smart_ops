#!/usr/bin/env python3
"""Build ONNX alignment models for mock-vs-yolo comparison test.

Exports a pre-trained MobileNetV2 classifier to ONNX format for the YOLO backend.
The model predicts ImageNet classes; we map them to hotpot domain classes.

This is a _comparison model_, not production-trained — its purpose is to
exercise the full ONNX inference pipeline and produce output structurally
identical to what a trained model would yield.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch
import torchvision

TABLE_CLASS_NAMES = ("empty", "dining", "need_clean", "checkout")
KITCHEN_CLASS_NAMES = ("kitchen_ok", "kitchen_no_hat", "kitchen_no_mask", "kitchen_smoke")


def export_classifier(out_path: Path, num_classes: int) -> None:
    """Export a MobileNetV2 classifier head with num_classes outputs."""
    model = torchvision.models.mobilenet_v2(weights="IMAGENET1K_V1")

    # Replace classifier head
    in_features = model.classifier[1].in_features
    model.classifier[1] = torch.nn.Linear(in_features, num_classes)

    # Use ImageNet weights for feature extractor, random for new head
    model.eval()

    dummy = torch.randn(1, 3, 224, 224)

    torch.onnx.export(
        model,
        dummy,
        str(out_path),
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={"input": {0: "batch"}},
        opset_version=14,
    )
    print(f"[OK] Exported {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="models")
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    export_classifier(out_dir / "table_state.onnx", 4)
    export_classifier(out_dir / "kitchen_compliance.onnx", 4)

    print(f"[OK] Models written to {out_dir.absolute()}")
    print("  table_state.onnx    — 4 classes: empty, dining, need_clean, checkout")
    print("  kitchen_compliance.onnx — 4 classes: kitchen_ok, kitchen_no_hat, kitchen_no_mask, kitchen_smoke")


if __name__ == "__main__":
    main()
