"""CV ingredient freshness and quality inspection for receiving dock.

The module reuses the shared YOLO detector where available, then applies
lightweight CV heuristics for discoloration, wilting, and foreign objects.
Set ``MOCK_QUALITY=1`` or ``HOTPOT_DEV_MODE=1`` for deterministic dev output.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

logger = logging.getLogger("receiving.ingredient_quality")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
QUALITY_THRESHOLD = int(os.environ.get("RECEIVING_QUALITY_THRESHOLD", "75"))
FOREIGN_LABELS = {"person", "staff", "customer", "knife", "utensil", "bottle", "container", "cell phone"}
INGREDIENT_LABELS = {"food", "apple", "banana", "orange", "broccoli", "carrot", "meat", "vegetable", "seafood"}


def utc_now_iso() -> str:
    """Return current UTC timestamp without microseconds."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class QualityInspectionResult:
    """Structured ingredient quality result."""

    quality_score: int
    alert: bool
    threshold: int
    findings: List[Dict[str, Any]]
    detections: List[Dict[str, Any]]
    timestamp: str
    image_ref: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize quality inspection result."""
        return {
            "quality_score": self.quality_score,
            "alert": self.alert,
            "threshold": self.threshold,
            "findings": self.findings,
            "detections": self.detections,
            "timestamp": self.timestamp,
            "image_ref": self.image_ref,
            "metrics": self.metrics,
        }


class _MockQualityDetector:
    """Small detector shim used when real YOLO is unavailable or disabled."""

    def detect(self, image: np.ndarray, zone: str = "receiving") -> Dict[str, Any]:
        h, w = image.shape[:2]
        return {
            "zone": zone,
            "backend": "mock_quality",
            "total_detections": 1,
            "label_counts": {"food": 1},
            "detections": [{
                "label": "food",
                "coco_name": "food",
                "confidence": 0.9,
                "bbox": [int(w * 0.15), int(h * 0.15), int(w * 0.85), int(h * 0.85)],
            }],
        }


class IngredientQualityInspector:
    """Inspect receiving images for freshness and contamination risks."""

    def __init__(self, threshold: int = QUALITY_THRESHOLD, detector: Optional[Any] = None) -> None:
        self.threshold = threshold
        self._detector = detector

    def inspect_image_path(self, image_path: str) -> QualityInspectionResult:
        """Load an image from disk and run quality inspection."""
        p = Path(image_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        image = cv2.imread(str(p))
        if image is None:
            raise FileNotFoundError(f"cannot read image: {image_path}")
        return self.inspect(image, image_ref=str(p))

    def inspect(self, image: np.ndarray, image_ref: str = "") -> QualityInspectionResult:
        """Run YOLO-assisted freshness and quality checks on one frame."""
        if image is None or image.size == 0:
            raise ValueError("image is empty")

        yolo_result = self._detect(image)
        detections = yolo_result.get("detections", [])
        findings: List[Dict[str, Any]] = []
        score = 100

        discoloration = self._detect_discoloration(image)
        if discoloration["triggered"]:
            score -= discoloration["penalty"]
            findings.append(discoloration)

        wilting = self._detect_wilting(image)
        if wilting["triggered"]:
            score -= wilting["penalty"]
            findings.append(wilting)

        foreign = self._detect_foreign_objects(detections)
        if foreign["triggered"]:
            score -= foreign["penalty"]
            findings.append(foreign)

        score = max(0, min(100, int(round(score))))
        return QualityInspectionResult(
            quality_score=score,
            alert=score < self.threshold,
            threshold=self.threshold,
            findings=findings,
            detections=detections,
            timestamp=utc_now_iso(),
            image_ref=image_ref,
            metrics={
                "detector_backend": yolo_result.get("backend"),
                "total_detections": yolo_result.get("total_detections", len(detections)),
                "label_counts": yolo_result.get("label_counts", {}),
            },
        )

    def _detect(self, image: np.ndarray) -> Dict[str, Any]:
        detector = self._get_detector()
        try:
            return detector.detect(image, zone="receiving")
        except TypeError:
            return detector.detect(image)

    def _get_detector(self) -> Any:
        if self._detector is not None:
            return self._detector
        if os.environ.get("MOCK_QUALITY") == "1" or os.environ.get("HOTPOT_DEV_MODE") == "1":
            self._detector = _MockQualityDetector()
            return self._detector

        try:
            if str(PROJECT_ROOT) not in sys.path:
                sys.path.insert(0, str(PROJECT_ROOT))
            from edge.common.detector.real_yolo import RealYoloDetector
            self._detector = RealYoloDetector(conf=float(os.environ.get("RECEIVING_YOLO_CONF", "0.25")))
        except Exception as exc:
            logger.warning("real YOLO unavailable for quality inspection: %s", exc)
            self._detector = _MockQualityDetector()
        return self._detector

    def _detect_discoloration(self, image: np.ndarray) -> Dict[str, Any]:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        saturation = hsv[:, :, 1]
        value = hsv[:, :, 2]
        brown_mask = cv2.inRange(hsv, (5, 30, 20), (35, 220, 180))
        dark_mask = cv2.inRange(value, 0, 45)
        dull_mask = ((saturation < 35) & (value < 150)).astype(np.uint8) * 255
        ratio = float(np.count_nonzero(brown_mask | dark_mask | dull_mask)) / max(image.shape[0] * image.shape[1], 1)
        triggered = ratio > float(os.environ.get("QUALITY_DISCOLORATION_RATIO", "0.28"))
        return {
            "type": "discoloration",
            "triggered": triggered,
            "severity": "warning" if ratio < 0.45 else "critical",
            "confidence": round(min(0.95, 0.45 + ratio), 3),
            "penalty": 22 if ratio < 0.45 else 35,
            "metrics": {"affected_ratio": round(ratio, 4)},
        }

    def _detect_wilting(self, image: np.ndarray) -> Dict[str, Any]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        green_mask = cv2.inRange(hsv, (35, 25, 25), (90, 255, 255))
        green_ratio = float(np.count_nonzero(green_mask)) / max(image.shape[0] * image.shape[1], 1)
        blurry_leaf = green_ratio > 0.12 and lap_var < float(os.environ.get("QUALITY_WILTING_LAPLACIAN", "55"))
        triggered = bool(blurry_leaf)
        return {
            "type": "wilting",
            "triggered": triggered,
            "severity": "warning",
            "confidence": round(0.7 if triggered else 0.25, 3),
            "penalty": 18,
            "metrics": {"green_ratio": round(green_ratio, 4), "laplacian_var": round(lap_var, 2)},
        }

    def _detect_foreign_objects(self, detections: List[Dict[str, Any]]) -> Dict[str, Any]:
        hits = []
        for det in detections:
            label = str(det.get("label") or det.get("class_name") or det.get("coco_name") or "").lower()
            coco = str(det.get("coco_name") or "").lower()
            if label in FOREIGN_LABELS or coco in FOREIGN_LABELS:
                hits.append(det)
        return {
            "type": "foreign_objects",
            "triggered": bool(hits),
            "severity": "critical" if hits else "info",
            "confidence": max([float(h.get("confidence", 0.7)) for h in hits], default=0.0),
            "penalty": 40,
            "objects": hits,
            "metrics": {"count": len(hits)},
        }
