#!/usr/bin/env python3
"""
Hotpot edge vision detector PoC.

Supports two backends:
- mock: rule/heuristic demo without trained weights (default)
- onnx: reuse Detect_Inference_Project ONNX pipeline when available

Detects front-of-house table states and back-of-kitchen compliance events.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from common.schemas import TABLE_STATES, EventLevel, EventSource, OpsEvent, TableState, utc_now_iso

DETECT_PROJECT = Path("/home/liuwz/Detect_Inference_Project")

TABLE_LABELS = {
    0: ("empty", EventLevel.INFO),
    1: ("dining", EventLevel.INFO),
    2: ("need_clean", EventLevel.WARN),
    3: ("checkout", EventLevel.INFO),
}

KITCHEN_LABELS = {
    0: ("kitchen_no_hat", EventLevel.WARN),
    1: ("kitchen_no_mask", EventLevel.WARN),
    2: ("kitchen_smoke", EventLevel.CRITICAL),
}


class MockHotpotDetector:
    """Heuristic/mock detector for PoC demo without trained models."""

    TABLE_COLORS = {
        "empty": (80, 180, 80),
        "dining": (60, 120, 220),
        "need_clean": (40, 160, 220),
        "checkout": (200, 140, 60),
    }

    def __init__(self, store_id: str = "store_yuhuan") -> None:
        self.store_id = store_id

    def _infer_table_state_from_roi(self, roi: np.ndarray, table_id: str) -> TableState:
        h, w = roi.shape[:2]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        mean_brightness = float(np.mean(gray))
        edges = cv2.Canny(gray, 50, 150)
        edge_density = float(np.count_nonzero(edges)) / max(h * w, 1)

        # Deterministic pseudo-state from table_id hash for stable demo
        seed = sum(ord(c) for c in table_id) % 4
        if edge_density > 0.08 and mean_brightness < 120:
            state = "dining"
        elif mean_brightness > 150 and edge_density < 0.04:
            state = "empty"
        elif edge_density > 0.06:
            state = "need_clean"
        else:
            states = ["empty", "dining", "need_clean", "checkout"]
            state = states[seed]

        return TableState(table_id=table_id, state=state, confidence=0.75 + seed * 0.05)

    def detect_tables(self, image: np.ndarray, table_regions: Optional[List[Dict]] = None) -> List[TableState]:
        h, w = image.shape[:2]
        if table_regions is None:
            # Default 4x2 grid for demo
            table_regions = []
            cols, rows = 4, 2
            for r in range(rows):
                for c in range(cols):
                    tid = f"T{r * cols + c + 1:02d}"
                    x1 = int(c * w / cols + w * 0.02)
                    y1 = int(r * h / rows + h * 0.05)
                    x2 = int((c + 1) * w / cols - w * 0.02)
                    y2 = int((r + 1) * h / rows - h * 0.05)
                    table_regions.append({"table_id": tid, "bbox": [x1, y1, x2, y2]})

        results: List[TableState] = []
        for region in table_regions:
            x1, y1, x2, y2 = region["bbox"]
            roi = image[y1:y2, x1:x2]
            if roi.size == 0:
                continue
            results.append(self._infer_table_state_from_roi(roi, region["table_id"]))
        return results

    def detect_kitchen(self, image: np.ndarray) -> List[OpsEvent]:
        events: List[OpsEvent] = []
        h, w = image.shape[:2]
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

        # Smoke/fire proxy: high saturation + value in upper region
        upper = hsv[: h // 2, :]
        smoke_mask = cv2.inRange(upper, (0, 0, 180), (180, 80, 255))
        smoke_ratio = float(np.count_nonzero(smoke_mask)) / max(upper.size // 3, 1)
        if smoke_ratio > 0.02:
            events.append(
                OpsEvent(
                    event_type="kitchen_smoke",
                    source=EventSource.VISION.value,
                    level=EventLevel.CRITICAL.value,
                    store_id=self.store_id,
                    zone="kitchen",
                    message="检测到后厨烟雾/明火异常",
                    confidence=min(0.95, 0.6 + smoke_ratio * 5),
                    metadata={"smoke_ratio": round(smoke_ratio, 4)},
                )
            )

        # Skin-tone proxy in center for no-hat/no-mask demo
        center = image[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4]
        ycrcb = cv2.cvtColor(center, cv2.COLOR_BGR2YCrCb)
        skin_mask = cv2.inRange(ycrcb, (0, 133, 77), (255, 173, 127))
        skin_ratio = float(np.count_nonzero(skin_mask)) / max(center.shape[0] * center.shape[1], 1)
        if skin_ratio > 0.15:
            events.append(
                OpsEvent(
                    event_type="kitchen_no_hat",
                    source=EventSource.VISION.value,
                    level=EventLevel.WARN.value,
                    store_id=self.store_id,
                    zone="kitchen",
                    message="后厨人员可能未佩戴厨师帽",
                    confidence=min(0.9, 0.5 + skin_ratio),
                    metadata={"skin_ratio": round(skin_ratio, 4)},
                )
            )
        return events

    def table_states_to_events(self, states: List[TableState]) -> List[OpsEvent]:
        events: List[OpsEvent] = []
        for ts in states:
            level = EventLevel.WARN if ts.state == "need_clean" else EventLevel.INFO
            msg_map = {
                "empty": "空桌可入座",
                "dining": "用餐中",
                "need_clean": "待清台",
                "checkout": "待结账",
            }
            events.append(
                OpsEvent(
                    event_type=f"table_{ts.state}",
                    source=EventSource.VISION.value,
                    level=level.value,
                    store_id=self.store_id,
                    zone="front",
                    table_id=ts.table_id,
                    message=f"桌位 {ts.table_id}: {msg_map.get(ts.state, ts.state)}",
                    confidence=ts.confidence,
                )
            )
        return events

    def annotate(self, image: np.ndarray, table_states: List[TableState]) -> np.ndarray:
        out = image.copy()
        h, w = out.shape[:2]
        cols, rows = 4, 2
        for ts in table_states:
            idx = int(ts.table_id.replace("T", "")) - 1
            r, c = divmod(idx, cols)
            x1 = int(c * w / cols + w * 0.02)
            y1 = int(r * h / rows + h * 0.05)
            x2 = int((c + 1) * w / cols - w * 0.02)
            y2 = int((r + 1) * h / rows - h * 0.05)
            color = self.TABLE_COLORS.get(ts.state, (200, 200, 200))
            cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                out,
                f"{ts.table_id}:{ts.state}",
                (x1 + 5, y1 + 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
            )
        return out


class YoloOnnxDetector(MockHotpotDetector):
    """ONNX ROI classifier backend (table + kitchen models in models/)."""

    def __init__(self, store_id: str = "store_yuhuan") -> None:
        super().__init__(store_id)
        from edge.detector.yolo_onnx import load_kitchen_classifier, load_table_classifier

        self._table_cls = load_table_classifier()
        self._kitchen_cls = load_kitchen_classifier()
        self._available = self._table_cls is not None or self._kitchen_cls is not None

    @property
    def available(self) -> bool:
        return self._available

    def detect_tables(self, image: np.ndarray, table_regions: Optional[List[Dict]] = None) -> List[TableState]:
        if not self._table_cls:
            return super().detect_tables(image, table_regions)
        h, w = image.shape[:2]
        if table_regions is None:
            table_regions = []
            cols, rows = 4, 2
            for r in range(rows):
                for c in range(cols):
                    tid = f"T{r * cols + c + 1:02d}"
                    x1 = int(c * w / cols + w * 0.02)
                    y1 = int(r * h / rows + h * 0.05)
                    x2 = int((c + 1) * w / cols - w * 0.02)
                    y2 = int((r + 1) * h / rows - h * 0.05)
                    table_regions.append({"table_id": tid, "bbox": [x1, y1, x2, y2]})
        results: List[TableState] = []
        for region in table_regions:
            x1, y1, x2, y2 = region["bbox"]
            roi = image[y1:y2, x1:x2]
            if roi.size == 0:
                continue
            state, conf = self._table_cls.predict(roi)
            if state not in TABLE_STATES:
                state = "empty"
            results.append(TableState(table_id=region["table_id"], state=state, confidence=conf))
        return results

    def detect_kitchen(self, image: np.ndarray) -> List[OpsEvent]:
        if not self._kitchen_cls:
            return super().detect_kitchen(image)
        label, conf = self._kitchen_cls.predict(image)
        if label == "kitchen_ok":
            return []
        level = EventLevel.CRITICAL if label == "kitchen_smoke" else EventLevel.WARN
        msg_map = {
            "kitchen_no_hat": "后厨人员可能未佩戴厨师帽",
            "kitchen_no_mask": "后厨人员可能未佩戴口罩",
            "kitchen_smoke": "检测到后厨烟雾/明火异常",
        }
        return [
            OpsEvent(
                event_type=label,
                source=EventSource.VISION.value,
                level=level.value,
                store_id=self.store_id,
                zone="kitchen",
                message=msg_map.get(label, label),
                confidence=conf,
                metadata={"yolo_label": label},
            )
        ]


class OnnxHotpotDetector(MockHotpotDetector):
    """Optional ONNX backend wrapping Detect_Inference_Project when available."""

    def __init__(self, store_id: str = "store_yuhuan", detect_root: Optional[Path] = None) -> None:
        super().__init__(store_id)
        self.detect_root = detect_root or DETECT_PROJECT
        self._detect_model = None
        self._class_model = None
        self._available = False
        self._try_load()

    def _try_load(self) -> None:
        if not self.detect_root.exists():
            return
        try:
            sys.path.insert(0, str(self.detect_root))
            from DETECT_onnx import DETECT_MODEL, CLASS_MODEL  # type: ignore

            detect_path = self.detect_root / "MODEL" / "detect.onnx"
            class_path = self.detect_root / "MODEL" / "class.onnx"
            if not detect_path.exists():
                return
            self._detect_model = DETECT_MODEL()
            self._detect_model.load_model(str(detect_path))
            if class_path.exists():
                self._class_model = CLASS_MODEL()
                self._class_model.load_model(str(class_path))
            self._available = True
        except Exception as exc:
            print(f"[WARN] ONNX backend unavailable, using mock: {exc}", file=sys.stderr)

    @property
    def available(self) -> bool:
        return self._available


def create_detector(backend: str = "mock", store_id: str = "store_yuhuan"):
    if backend == "rknn":
        from edge.detector.rknn_backend import RknnHotpotDetector

        det = RknnHotpotDetector(store_id=store_id)
        if det.available:
            return det
        print("[WARN] RKNN unavailable, falling back to yolo/mock")
    if backend == "yolo":
        det = YoloOnnxDetector(store_id=store_id)
        if det.available:
            return det
        print("[WARN] YOLO ONNX models not found, falling back to mock")
    if backend == "onnx":
        det = OnnxHotpotDetector(store_id=store_id)
        if det.available:
            return det
        print("[WARN] Falling back to mock detector")
    return MockHotpotDetector(store_id=store_id)


def run_on_frame(
    image: np.ndarray,
    backend: str = "mock",
    store_id: str = "store_yuhuan",
    zone: str = "front",
    table_regions: Optional[List[Dict]] = None,
    image_label: str = "",
    annotated_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    detector = create_detector(backend, store_id)
    result: Dict[str, Any] = {
        "store_id": store_id,
        "zone": zone,
        "image": image_label,
        "timestamp": utc_now_iso(),
        "backend": (
            backend
            if (
                (isinstance(detector, YoloOnnxDetector) and detector.available)
                or (isinstance(detector, OnnxHotpotDetector) and detector.available)
                or (type(detector).__name__ == "RknnHotpotDetector" and getattr(detector, "available", False))
            )
            else "mock"
        ),
    }

    if zone == "front":
        table_states = detector.detect_tables(image, table_regions=table_regions)
        events = detector.table_states_to_events(table_states)
        annotated = detector.annotate(image, table_states)
        result["table_states"] = [ts.to_dict() for ts in table_states]
        result["turnover_suggestions"] = _build_turnover_suggestions(table_states)
    else:
        events = detector.detect_kitchen(image)
        annotated = image.copy()
        for i, ev in enumerate(events):
            cv2.putText(
                annotated,
                ev.event_type,
                (20, 40 + 30 * i),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 0, 255),
                2,
            )
        result["table_states"] = []

    result["events"] = [e.to_dict() for e in events]
    stem = Path(image_label).stem if image_label else zone
    out_dir = annotated_dir or (Path(image_label).parent if image_label else Path("."))
    out_path = out_dir / f"{stem}_annotated.jpg"
    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), annotated)
    result["annotated_image"] = str(out_path)
    return result


def run_on_image(
    image_path: Path,
    backend: str = "mock",
    store_id: str = "store_yuhuan",
    zone: str = "front",
    table_regions: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(f"Cannot read image: {image_path}")
    return run_on_frame(
        image,
        backend=backend,
        store_id=store_id,
        zone=zone,
        table_regions=table_regions,
        image_label=str(image_path),
        annotated_dir=image_path.parent,
    )


def _build_turnover_suggestions(states: List[TableState]) -> List[Dict[str, Any]]:
    priority = {"need_clean": 1, "checkout": 2, "empty": 3, "dining": 4}
    sorted_states = sorted(states, key=lambda s: (priority.get(s.state, 99), s.table_id))
    suggestions = []
    for ts in sorted_states:
        if ts.state in ("need_clean", "checkout", "empty"):
            action = {"need_clean": "立即清台", "checkout": "引导结账", "empty": "可安排入座"}.get(ts.state, "")
            suggestions.append(
                {
                    "table_id": ts.table_id,
                    "state": ts.state,
                    "action": action,
                    "priority": priority.get(ts.state, 99),
                }
            )
    return suggestions


def main() -> None:
    parser = argparse.ArgumentParser(description="Hotpot edge vision detector")
    parser.add_argument("--image", required=True, help="Input image path")
    parser.add_argument("--zone", choices=("front", "kitchen"), default="front")
    parser.add_argument("--backend", choices=("mock", "onnx", "yolo", "rknn"), default="mock")
    parser.add_argument("--store-id", default="store_yuhuan")
    parser.add_argument("--hub-url", default="", help="POST events to event hub")
    parser.add_argument("--output", default="", help="Write JSON result to file")
    parser.add_argument("--config-dir", default="", help="UAT config dir, loads ROI for front zone")
    args = parser.parse_args()

    table_regions = None
    if args.zone == "front":
        from common.store_config import DEFAULT_UAT_ROOT, table_regions_for_frame
        import cv2 as _cv2

        img = _cv2.imread(args.image)
        if img is not None:
            h, w = img.shape[:2]
            uat_root = Path(args.config_dir) if args.config_dir else DEFAULT_UAT_ROOT
            table_regions = table_regions_for_frame(args.store_id, w, h, uat_root)

    result = run_on_image(Path(args.image), args.backend, args.store_id, args.zone, table_regions=table_regions)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    print(payload)

    if args.hub_url:
        from common.hub_client import EdgeHubClient

        config_key = os.environ.get("HOTPOT_API_KEY", "")
        client = EdgeHubClient(args.hub_url, args.store_id, api_key=config_key)
        client.post_events(result["events"])
        if result.get("table_states"):
            client.post_tables(result["table_states"])


if __name__ == "__main__":
    main()
