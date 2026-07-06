"""YOLO/ONNX inference helpers for hotpot vision (P0 model path)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_DIR = PROJECT_ROOT / "models"

TABLE_CLASS_NAMES = ("empty", "dining", "need_clean", "checkout")
KITCHEN_CLASS_NAMES = ("kitchen_ok", "kitchen_no_hat", "kitchen_no_mask", "kitchen_smoke")

try:
    import onnxruntime as ort

    _ORT_AVAILABLE = True
except ImportError:
    ort = None  # type: ignore
    _ORT_AVAILABLE = False


def resolve_model_path(name: str, env_key: str) -> Optional[Path]:
    env = os.environ.get(env_key, "")
    if env:
        p = Path(env)
        return p if p.exists() else None
    for candidate in (DEFAULT_MODEL_DIR / name, PROJECT_ROOT / "models" / name):
        if candidate.exists():
            return candidate
    return None


def preprocess_cls(bgr: np.ndarray, size: int = 224) -> np.ndarray:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    resized = cv2.resize(rgb, (size, size))
    arr = resized.astype(np.float32) / 255.0
    arr = (arr - np.array([0.485, 0.456, 0.406], dtype=np.float32)) / np.array(
        [0.229, 0.224, 0.225], dtype=np.float32
    )
    return np.transpose(arr, (2, 0, 1))[np.newaxis, ...]


class OnnxClassifier:
    """Generic ONNX image classifier (NCHW float32 input)."""

    def __init__(self, model_path: Path, class_names: Tuple[str, ...]) -> None:
        if not _ORT_AVAILABLE:
            raise RuntimeError("onnxruntime not installed; pip install onnxruntime")
        self.class_names = class_names
        self.session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
        self.input_name = self.session.get_inputs()[0].name

    def predict(self, bgr: np.ndarray) -> Tuple[str, float]:
        if bgr.size == 0:
            return self.class_names[0], 0.0
        inp = preprocess_cls(bgr)
        outputs = self.session.run(None, {self.input_name: inp})
        logits = outputs[0][0]
        if logits.ndim == 0:
            idx = int(logits)
            conf = 1.0
        else:
            exp = np.exp(logits - np.max(logits))
            probs = exp / exp.sum()
            idx = int(np.argmax(probs))
            conf = float(probs[idx])
        idx = min(idx, len(self.class_names) - 1)
        return self.class_names[idx], conf


def load_table_classifier() -> Optional[OnnxClassifier]:
    path = resolve_model_path("table_state.onnx", "HOTPOT_TABLE_MODEL")
    if not path:
        return None
    try:
        return OnnxClassifier(path, TABLE_CLASS_NAMES)
    except Exception as exc:
        print(f"[yolo_onnx] table model load failed: {exc}")
        return None


def load_kitchen_classifier() -> Optional[OnnxClassifier]:
    path = resolve_model_path("kitchen_compliance.onnx", "HOTPOT_KITCHEN_MODEL")
    if not path:
        return None
    try:
        return OnnxClassifier(path, KITCHEN_CLASS_NAMES)
    except Exception as exc:
        print(f"[yolo_onnx] kitchen model load failed: {exc}")
        return None
