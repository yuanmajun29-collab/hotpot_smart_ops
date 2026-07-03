#!/usr/bin/env python3
"""Export stub ONNX classifier models for hotpot_smart_ops PoC pipeline.

Creates two models:
  - table_state.onnx    (4 classes: empty, dining, need_clean, checkout)
  - kitchen_compliance.onnx  (4 classes: kitchen_ok, kitchen_no_hat, kitchen_no_mask, kitchen_smoke)

Both accept NCHW float32 input [1,3,224,224] and output 4-class logits.
Uses torch.onnx.export — no torchvision/ultralytics/onnx needed.

These are stub models with random weights. Replace with trained models
when real火锅 scene data becomes available.
"""

from __future__ import annotations

import sys
from pathlib import Path

import torch
import torch.nn as nn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = PROJECT_ROOT / "models"


class StubClassifier(nn.Module):
    """Lightweight CNN classifier matching OnnxClassifier expectations.

    Input:  [1, 3, 224, 224]  (NCHW float32, RGB, normalized)
    Output: [1, num_classes]  (logits)
    """

    def __init__(self, num_classes: int = 4) -> None:
        super().__init__()
        self.features = nn.Sequential(
            # 224 -> 112
            nn.Conv2d(3, 32, kernel_size=3, stride=2, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            # 112 -> 56
            nn.Conv2d(32, 64, kernel_size=3, stride=2, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            # 56 -> 28
            nn.Conv2d(64, 128, kernel_size=3, stride=2, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            # 28 -> 14
            nn.Conv2d(128, 256, kernel_size=3, stride=2, padding=1),
            nn.BatchNorm2d(256),
            nn.ReLU(inplace=True),
            # 14 -> 7
            nn.Conv2d(256, 512, kernel_size=3, stride=2, padding=1),
            nn.BatchNorm2d(512),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((1, 1)),
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Linear(512, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.classifier(self.features(x))


def export(model_name: str, num_classes: int) -> Path:
    model = StubClassifier(num_classes=num_classes)
    model.eval()

    out_path = MODEL_DIR / f"{model_name}.onnx"
    dummy_input = torch.randn(1, 3, 224, 224)

    torch.onnx.export(
        model,
        dummy_input,
        str(out_path),
        input_names=["input"],
        output_names=["logits"],
        dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=17,
    )

    print(f"[OK] {out_path}  ({out_path.stat().st_size / 1024:.0f} KB)")
    return out_path


def verify(model_path: Path) -> None:
    import numpy as np
    import onnxruntime as ort

    sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    input_name = sess.get_inputs()[0].name
    dummy = np.random.randn(1, 3, 224, 224).astype(np.float32)
    out = sess.run(None, {input_name: dummy})[0]
    print(f"[verify] {model_path.name}: input={dummy.shape} → output={out.shape}")


def main() -> int:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    export("table_state", 4)
    export("kitchen_compliance", 4)

    verify(MODEL_DIR / "table_state.onnx")
    verify(MODEL_DIR / "kitchen_compliance.onnx")

    print("\nDone. Place in models/ and run with --backend yolo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
