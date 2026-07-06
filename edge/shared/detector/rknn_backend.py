"""RKNN NPU detector wrapper with graceful fallback (DEV-204)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from edge.detector.hotpot_detector import MockHotpotDetector
from common.schemas import EventLevel, EventSource, OpsEvent, TableState

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RKNN_MODEL = PROJECT_ROOT / "edge" / "rknn_deploy" / "output" / "hotpot_detect.rknn"

# Class index → table state (customize after training)
RKNN_TABLE_CLASSES = ("empty", "dining", "need_clean", "checkout")
RKNN_KITCHEN_CLASSES = ("kitchen_ok", "kitchen_no_hat", "kitchen_no_mask", "kitchen_smoke")


class RknnHotpotDetector(MockHotpotDetector):
    """RKNN runtime detector; falls back to YOLO ONNX or mock when NPU unavailable."""

    def __init__(self, store_id: str = "store_yuhuan", model_path: Optional[Path] = None) -> None:
        super().__init__(store_id)
        self.model_path = model_path or Path(
            os.environ.get("HOTPOT_RKNN_MODEL", str(DEFAULT_RKNN_MODEL))
        )
        self._rknn = None
        self._available = False
        self._fallback = None
        self._try_load()

    def _try_load(self) -> None:
        if not self.model_path.exists():
            print(f"[rknn] model not found: {self.model_path}", file=sys.stderr)
            self._init_fallback()
            return
        try:
            from rknnlite.api import RKNNLite  # type: ignore

            rknn = RKNNLite()
            ret = rknn.load_rknn(str(self.model_path))
            if ret != 0:
                raise RuntimeError(f"load_rknn failed: {ret}")
            ret = rknn.init_runtime()
            if ret != 0:
                raise RuntimeError(f"init_runtime failed: {ret}")
            self._rknn = rknn
            self._available = True
            print(f"[rknn] loaded {self.model_path}", file=sys.stderr)
        except Exception as exc:
            print(f"[rknn] NPU unavailable ({exc}), using fallback", file=sys.stderr)
            self._init_fallback()

    def _init_fallback(self) -> None:
        from edge.detector.hotpot_detector import YoloOnnxDetector

        yolo = YoloOnnxDetector(self.store_id)
        if yolo.available:
            self._fallback = yolo
            print("[rknn] fallback → yolo onnx", file=sys.stderr)
        else:
            self._fallback = self
            print("[rknn] fallback → mock", file=sys.stderr)

    @property
    def available(self) -> bool:
        return self._available or (self._fallback is not None and self._fallback is not self)

    def _infer_roi(self, roi: np.ndarray) -> tuple:
        if self._rknn is None:
            return "", 0.0
        inp = cv2.resize(roi, (224, 224))
        inp = cv2.cvtColor(inp, cv2.COLOR_BGR2RGB)
        outputs = self._rknn.inference(inputs=[np.expand_dims(inp, 0)])
        if not outputs:
            return RKNN_TABLE_CLASSES[0], 0.0
        logits = outputs[0].flatten()
        idx = int(np.argmax(logits))
        conf = float(np.max(logits) / (np.sum(np.abs(logits)) + 1e-6))
        idx = min(idx, len(RKNN_TABLE_CLASSES) - 1)
        return RKNN_TABLE_CLASSES[idx], min(conf, 1.0)

    def detect_tables(self, image: np.ndarray, table_regions: Optional[List[Dict]] = None) -> List[TableState]:
        if not self._available:
            fb = self._fallback or self
            return fb.detect_tables(image, table_regions)
        h, w = image.shape[:2]
        if table_regions is None:
            return super().detect_tables(image, table_regions)
        results: List[TableState] = []
        for region in table_regions:
            x1, y1, x2, y2 = region["bbox"]
            roi = image[y1:y2, x1:x2]
            if roi.size == 0:
                continue
            state, conf = self._infer_roi(roi)
            results.append(TableState(table_id=region["table_id"], state=state, confidence=conf))
        return results

    def detect_kitchen(self, image: np.ndarray) -> List[OpsEvent]:
        if not self._available:
            fb = self._fallback or self
            return fb.detect_kitchen(image)
        state, conf = self._infer_roi(image)
        if state in ("kitchen_ok", "empty"):
            return super().detect_kitchen(image)
        level = EventLevel.CRITICAL if state == "kitchen_smoke" else EventLevel.WARN
        return [
            OpsEvent(
                event_type=state if state.startswith("kitchen_") else "kitchen_smoke",
                source=EventSource.VISION.value,
                level=level.value,
                store_id=self.store_id,
                zone="kitchen",
                message=f"RKNN 检测: {state}",
                confidence=conf,
                metadata={"backend": "rknn"},
            )
        ]

    def release(self) -> None:
        if self._rknn is not None:
            try:
                self._rknn.release()
            except Exception:
                pass
            self._rknn = None
