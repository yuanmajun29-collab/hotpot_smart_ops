#!/usr/bin/env python3
"""Real YOLO detector via ultralytics — replaces mock for live demo."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# YOLO class names for COCO (yolov8n default)
COCO_NAMES = {
    0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 4: "airplane",
    5: "bus", 6: "train", 7: "truck", 8: "boat", 9: "traffic light",
    10: "fire hydrant", 11: "stop sign", 12: "parking meter", 13: "bench",
    14: "bird", 15: "cat", 16: "dog", 17: "horse", 18: "sheep", 19: "cow",
    20: "elephant", 21: "bear", 22: "zebra", 23: "giraffe", 24: "backpack",
    25: "umbrella", 26: "handbag", 27: "tie", 28: "suitcase", 29: "frisbee",
    30: "skis", 31: "snowboard", 32: "sports ball", 33: "kite", 34: "baseball bat",
    35: "baseball glove", 36: "skateboard", 37: "surfboard", 38: "tennis racket",
    39: "bottle", 40: "wine glass", 41: "cup", 42: "fork", 43: "knife",
    44: "spoon", 45: "bowl", 46: "banana", 47: "apple", 48: "sandwich",
    49: "orange", 50: "broccoli", 51: "carrot", 52: "hot dog", 53: "pizza",
    54: "donut", 55: "cake", 56: "chair", 57: "couch", 58: "potted plant",
    59: "bed", 60: "dining table", 61: "toilet", 62: "tv", 63: "laptop",
    64: "mouse", 65: "remote", 66: "keyboard", 67: "cell phone", 68: "microwave",
    69: "oven", 70: "toaster", 71: "sink", 72: "refrigerator", 73: "book",
    74: "clock", 75: "vase", 76: "scissors", 77: "teddy bear", 78: "hair drier",
    79: "toothbrush",
}

# Hotpot-relevant classes
HOTPOT_CLASSES = {
    "kitchen": {
        "person": "staff",
        "bottle": "container",
        "cup": "container",
        "bowl": "tableware",
        "fork": "utensil",
        "knife": "utensil",
        "spoon": "utensil",
        "oven": "appliance",
        "microwave": "appliance",
        "refrigerator": "appliance",
        "sink": "appliance",
        "dining table": "table",
        "chair": "chair",
    },
    "front": {
        "person": "customer",
        "dining table": "table",
        "chair": "chair",
        "bottle": "drink",
        "cup": "drink",
        "bowl": "tableware",
        "fork": "utensil",
        "knife": "utensil",
        "spoon": "utensil",
        "pizza": "food",
        "hot dog": "food",
        "sandwich": "food",
        "cake": "food",
        "donut": "food",
        "apple": "food",
        "banana": "food",
        "orange": "food",
        "broccoli": "food",
        "carrot": "food",
    },
}

# Bounding box colors per hotpot label
LABEL_COLORS = {
    "staff": (0, 165, 255),       # orange
    "customer": (255, 100, 0),    # blue
    "table": (0, 255, 127),       # spring green
    "chair": (200, 200, 200),     # light gray
    "tableware": (255, 255, 0),   # cyan
    "utensil": (255, 255, 0),     # cyan
    "container": (0, 255, 255),   # yellow
    "drink": (0, 255, 255),       # yellow
    "food": (0, 100, 255),        # orange-red
    "appliance": (255, 0, 0),     # red
}


class RealYoloDetector:
    """Real YOLO detector using ultralytics."""

    def __init__(self, model_name: str = "yolov8n.pt", conf: float = 0.3):
        from ultralytics import YOLO
        self.model = YOLO(model_name)
        self.conf = conf
        self._warm: bool = False

    def _warmup(self, h: int = 640, w: int = 640) -> None:
        if self._warm:
            return
        dummy = np.random.randint(0, 255, (h, w, 3), dtype=np.uint8)
        self.model(dummy, conf=self.conf, verbose=False)
        self._warm = True

    def detect(
        self,
        image: np.ndarray,
        zone: str = "kitchen",
    ) -> Dict[str, Any]:
        """Run inference, return structured results."""
        t0 = time.perf_counter()
        self._warmup()
        results = self.model(image, conf=self.conf, verbose=False)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        detections: List[Dict[str, Any]] = []
        annotated = image.copy()

        zone_map = HOTPOT_CLASSES.get(zone, {})

        if results and results[0].boxes is not None:
            boxes = results[0].boxes
            for box in boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                conf_val = float(box.conf[0])
                cls_id = int(box.cls[0])
                coco_name = COCO_NAMES.get(cls_id, f"cls_{cls_id}")
                hotpot_label = zone_map.get(coco_name, coco_name)
                color = LABEL_COLORS.get(hotpot_label, (0, 255, 0))

                detections.append({
                    "class_id": cls_id,
                    "label": hotpot_label,
                    "coco_name": coco_name,
                    "confidence": round(conf_val, 3),
                    "bbox": [round(x1), round(y1), round(x2), round(y2)],
                })

                # Draw box
                cv2.rectangle(annotated, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
                label_text = f"{hotpot_label} {conf_val:.2f}"
                (tw, th), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                cv2.rectangle(annotated, (int(x1), int(y1) - th - 6), (int(x1) + tw + 4, int(y1)), color, -1)
                cv2.putText(annotated, label_text, (int(x1) + 2, int(y1) - 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        # Count by label
        label_counts: Dict[str, int] = {}
        for d in detections:
            lbl = d["label"]
            label_counts[lbl] = label_counts.get(lbl, 0) + 1

        return {
            "zone": zone,
            "backend": "yolo_real",
            "model": "yolov8n",
            "total_detections": len(detections),
            "inference_ms": round(elapsed_ms, 1),
            "label_counts": label_counts,
            "detections": detections,
        }

    def annotate_and_save(
        self,
        image: np.ndarray,
        zone: str = "kitchen",
        save_path: Optional[Path] = None,
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """Detect, annotate, optionally save. Returns (annotated_image, result_dict)."""
        result = self.detect(image, zone)
        annotated = image.copy()

        colors = LABEL_COLORS
        zone_map = HOTPOT_CLASSES.get(zone, {})

        for d in result["detections"]:
            x1, y1, x2, y2 = d["bbox"]
            color = colors.get(d["label"], (0, 255, 0))
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            label_text = f"{d['label']} {d['confidence']:.2f}"
            (tw, th), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(annotated, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
            cv2.putText(annotated, label_text, (x1 + 2, y1 - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        if save_path:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(save_path), annotated)

        return annotated, result
