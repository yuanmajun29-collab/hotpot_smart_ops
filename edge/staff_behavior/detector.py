#!/usr/bin/env python3
"""Staff behavior detector — YOLO person + PPE + abnormal behavior.

Detection pipeline:
  1. YOLO person detection → bounding boxes
  2. PPE compliance check (hat / apron / mask via color-ratio heuristics)
  3. Abnormal behavior: loitering (dwell time), whispering (head proximity),
     unauthorized zone entry

Usage:
    from edge.staff_behavior.detector import StaffBehaviorDetector
    detector = StaffBehaviorDetector()
    results = detector.detect(frame_path_or_array)
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# ── Environment / config ─────────────────────────────────────────
HUB_URL = os.environ.get("HOTPOT_HUB_URL", "http://192.168.2.85:8098")
STORE_ID = os.environ.get("HOTPOT_STORE_ID", "store_yuhuan")
ZONE = os.environ.get("HOTPOT_ZONE", "kitchen")
CAMERA_ID = os.environ.get("HOTPOT_CAMERA_ID", "cam_staff_01")

# ── Thresholds ───────────────────────────────────────────────────
LOITERING_DWELL_SEC = int(os.environ.get("STAFF_LOITER_DWELL_SEC", 30))
WHISPER_DISTANCE_PX = int(os.environ.get("STAFF_WHISPER_DIST_PX", 60))
PPE_HAT_COLOR_RATIO = float(os.environ.get("PPE_HAT_COLOR_RATIO", 0.15))
PPE_APRON_COLOR_RATIO = float(os.environ.get("PPE_APRON_COLOR_RATIO", 0.18))


@dataclass
class PersonDetection:
    """Single person detection result."""

    bbox: Tuple[int, int, int, int]  # x1, y1, x2, y2
    confidence: float
    person_id: str = ""  # tracking ID if available
    ppe_hat: bool = False
    ppe_apron: bool = False
    ppe_mask: bool = False
    dwell_sec: float = 0.0
    is_loitering: bool = False


@dataclass
class DetectionResult:
    """Full frame detection result."""

    frame_id: str
    timestamp: str
    store_id: str
    zone: str
    camera_id: str
    person_count: int = 0
    persons: List[PersonDetection] = field(default_factory=list)
    alerts: List[Dict[str, Any]] = field(default_factory=list)
    ppe_compliance_rate: float = 0.0
    whispering_pairs: int = 0
    loitering_count: int = 0


class StaffBehaviorDetector:
    """Staff behavior detection engine.

    Uses YOLO (ultralytics) for person detection, then applies
    heuristic-based PPE and behavior analysis.

    Not designed for real-time 30fps — target is ~1 FPS for surveillance.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        conf_threshold: float = 0.35,
    ) -> None:
        self.conf_threshold = conf_threshold
        self._model = None
        self._model_path = model_path

        # Per-camera tracking state: person_id → (last_seen, bbox, dwell_start, zone)
        self._track_state: Dict[str, Dict[str, Any]] = {}

        # Zone boundary definitions (normalized 0-1 coords or pixel regions)
        self._restricted_zones: Dict[str, List[Tuple[int, int, int, int]]] = {}

    def _load_model(self):
        if self._model is not None:
            return
        try:
            from ultralytics import YOLO

            path = self._model_path or os.environ.get(
                "HOTPOT_YOLO_MODEL", "yolov8n.pt"
            )
            self._model = YOLO(path)
        except ImportError:
            raise RuntimeError(
                "ultralytics required for YOLO detection: "
                "pip install ultralytics"
            )

    # ── Detection ────────────────────────────────────────────────

    def detect(
        self,
        frame: Any,
        camera_id: str = "",
        zone: str = "",
    ) -> DetectionResult:
        """Run full detection pipeline on a frame.

        Args:
            frame: numpy array (H,W,3), path string, or PIL Image.
            camera_id: Camera identifier for tracking continuity.
            zone: Zone name for zone-based alerts.
        """
        cam = camera_id or CAMERA_ID
        zn = zone or ZONE
        ts = datetime.now(timezone.utc).isoformat()

        self._load_model()
        results = self._model(frame, conf=self.conf_threshold, verbose=False)

        persons: List[PersonDetection] = []
        alerts: List[Dict[str, Any]] = []
        frame_id = hashlib.md5(ts.encode()).hexdigest()[:12]

        # Extract person detections (COCO class 0 = person)
        for r in results:
            if r.boxes is None:
                continue
            boxes = r.boxes.xyxy.cpu().numpy() if hasattr(
                r.boxes.xyxy, "cpu"
            ) else r.boxes.xyxy
            confs = r.boxes.conf.cpu().numpy() if hasattr(
                r.boxes.conf, "cpu"
            ) else r.boxes.conf
            clss = r.boxes.cls.cpu().numpy() if hasattr(
                r.boxes.cls, "cpu"
            ) else r.boxes.cls

            for i in range(len(boxes)):
                cls_id = int(clss[i]) if len(clss) > i else -1
                if cls_id != 0:  # COCO: 0=person
                    continue
                conf = float(confs[i])
                raw = boxes[i][:4]
                bbox = (int(raw[0]), int(raw[1]), int(raw[2]), int(raw[3]))

                p = PersonDetection(bbox=bbox, confidence=conf)

                # PPE check (heuristic: color ratios in top/bottom region)
                p.ppe_hat = self._check_ppe_hat(frame, bbox)
                p.ppe_apron = self._check_ppe_apron(frame, bbox)
                p.ppe_mask = False  # requires face detection not available here

                # Dwell / loitering check
                p.person_id = self._assign_track_id(bbox, cam)
                p.dwell_sec = self._update_dwell(p.person_id, bbox, cam, zn)
                p.is_loitering = p.dwell_sec > LOITERING_DWELL_SEC

                if p.is_loitering:
                    alerts.append(
                        {
                            "type": "loitering",
                            "person_id": p.person_id,
                            "bbox": list(bbox),
                            "dwell_sec": round(p.dwell_sec, 1),
                            "zone": zn,
                            "severity": "warning",
                        }
                    )

                persons.append(p)

        # Whispering detection: pairs of heads too close
        whisper_pairs = self._detect_whispering(persons)
        for wp in whisper_pairs:
            alerts.append(
                {
                    "type": "whispering",
                    "person_ids": [wp[0], wp[1]],
                    "distance_px": wp[2],
                    "severity": "info",
                }
            )

        # Unauthorized zone check
        zone_alerts = self._check_zone_intrusion(persons, zn)
        alerts.extend(zone_alerts)

        # PPE compliance
        ppe_ok = sum(
            1
            for p in persons
            if p.ppe_hat or p.ppe_apron
        )
        ppe_rate = (ppe_ok / len(persons) * 100) if persons else 100.0

        return DetectionResult(
            frame_id=frame_id,
            timestamp=ts,
            store_id=STORE_ID,
            zone=zn,
            camera_id=cam,
            person_count=len(persons),
            persons=persons,
            alerts=alerts,
            ppe_compliance_rate=round(ppe_rate, 1),
            whispering_pairs=len(whisper_pairs),
            loitering_count=sum(1 for p in persons if p.is_loitering),
        )

    # ── PPE Heuristics ───────────────────────────────────────────

    def _check_ppe_hat(
        self,
        frame: Any,
        bbox: Tuple[int, int, int, int],
    ) -> bool:
        """Check hat presence via brightness ratio in top 20% of person bbox."""
        x1, y1, x2, y2 = bbox
        try:
            if hasattr(frame, "read"):
                # If path string
                import cv2

                img = cv2.imread(str(frame)) if isinstance(frame, str) else frame
            else:
                img = frame

            if img is None or img.size == 0:
                return False

            h, w = img.shape[:2]
            x1_c = max(0, int(x1))
            y1_c = max(0, int(y1))
            x2_c = min(w, int(x2))
            y2_c = min(h, int(y2))

            head_h = max(1, int((y2_c - y1_c) * 0.22))
            head_region = img[y1_c : y1_c + head_h, x1_c:x2_c]

            if head_region.size == 0:
                return False

            # Simple ratio: if top region is significantly brighter/darker
            # than rest of person, likely has hat
            if len(head_region.shape) >= 2:
                head_mean = np.mean(head_region)
                body_region = img[
                    y1_c + head_h : y2_c, x1_c:x2_c
                ]
                if body_region.size == 0:
                    return False
                body_mean = np.mean(body_region)
                ratio = abs(head_mean - body_mean) / max(body_mean, 1)
                return ratio > PPE_HAT_COLOR_RATIO
            return False
        except Exception:
            return False

    def _check_ppe_apron(
        self,
        frame: Any,
        bbox: Tuple[int, int, int, int],
    ) -> bool:
        """Check apron via color saturation in lower 30% region."""
        x1, y1, x2, y2 = bbox
        try:
            if hasattr(frame, "read"):
                import cv2

                img = cv2.imread(str(frame)) if isinstance(frame, str) else frame
            else:
                img = frame

            if img is None or img.size == 0:
                return False

            h, w = img.shape[:2]
            x1_c = max(0, int(x1))
            y1_c = max(0, int(y1))
            x2_c = min(w, int(x2))
            y2_c = min(h, int(y2))

            person_h = y2_c - y1_c
            apron_start = y1_c + int(person_h * 0.55)
            apron_end = y2_c
            apron_region = img[apron_start:apron_end, x1_c:x2_c]

            if apron_region.size == 0:
                return False

            # Check for apron-like color (usually dark/saturated)
            apron_mean = np.mean(apron_region)
            upper_region = img[y1_c:apron_start, x1_c:x2_c]
            if upper_region.size == 0:
                return False
            upper_mean = np.mean(upper_region)
            ratio = abs(apron_mean - upper_mean) / max(upper_mean, 1)
            return ratio > PPE_APRON_COLOR_RATIO
        except Exception:
            return False

    # ── Behavior Analysis ────────────────────────────────────────

    def _assign_track_id(
        self,
        bbox: Tuple[int, int, int, int],
        camera_id: str,
    ) -> str:
        """Simple IoU-based tracking ID assignment (no deepsort dependency)."""
        cx = (bbox[0] + bbox[2]) / 2
        cy = (bbox[1] + bbox[3]) / 2

        if camera_id not in self._track_state:
            self._track_state[camera_id] = {}

        state = self._track_state[camera_id]

        # Find closest existing track (within threshold)
        best_id = None
        best_dist = float("inf")
        threshold = 60  # pixels

        for tid, info in state.items():
            last_cx = (info["bbox"][0] + info["bbox"][2]) / 2
            last_cy = (info["bbox"][1] + info["bbox"][3]) / 2
            dist = ((cx - last_cx) ** 2 + (cy - last_cy) ** 2) ** 0.5
            if dist < best_dist and dist < threshold:
                best_dist = dist
                best_id = tid

        if best_id is None:
            best_id = hashlib.md5(
                f"{camera_id}-{cx:.0f}-{cy:.0f}-{time.time():.3f}".encode()
            ).hexdigest()[:8]
            state[best_id] = {
                "bbox": bbox,
                "last_seen": time.time(),
                "dwell_start": time.time(),
                "zone": "",
            }
        else:
            state[best_id]["bbox"] = bbox
            state[best_id]["last_seen"] = time.time()

        # Cleanup stale tracks (>10s unseen)
        now = time.time()
        stale = [
            tid
            for tid, info in state.items()
            if now - info["last_seen"] > 10
        ]
        for tid in stale:
            del state[tid]

        return best_id

    def _update_dwell(
        self,
        person_id: str,
        bbox: Tuple[int, int, int, int],
        camera_id: str,
        zone: str,
    ) -> float:
        """Update dwell timer and return current dwell seconds."""
        state = self._track_state.get(camera_id, {})
        if person_id in state:
            dwell = time.time() - state[person_id]["dwell_start"]
            state[person_id]["zone"] = zone
            return dwell
        return 0.0

    def _detect_whispering(
        self,
        persons: List[PersonDetection],
    ) -> List[Tuple[str, str, float]]:
        """Detect whispering: two persons with heads very close."""
        pairs = []
        for i in range(len(persons)):
            for j in range(i + 1, len(persons)):
                p1, p2 = persons[i], persons[j]

                # Head region centers (top 25% of bbox)
                h1_y = p1.bbox[1] + (p1.bbox[3] - p1.bbox[1]) * 0.12
                h1_x = (p1.bbox[0] + p1.bbox[2]) / 2
                h2_y = p2.bbox[1] + (p2.bbox[3] - p2.bbox[1]) * 0.12
                h2_x = (p2.bbox[0] + p2.bbox[2]) / 2

                dist = ((h1_x - h2_x) ** 2 + (h1_y - h2_y) ** 2) ** 0.5
                if dist < WHISPER_DISTANCE_PX:
                    pairs.append(
                        (
                            p1.person_id or f"p{i}",
                            p2.person_id or f"p{j}",
                            round(dist, 1),
                        )
                    )
        return pairs

    def _check_zone_intrusion(
        self,
        persons: List[PersonDetection],
        zone: str,
    ) -> List[Dict[str, Any]]:
        """Check if any person is in a restricted zone."""
        alerts = []
        restricted = self._restricted_zones.get(zone, [])
        for p in persons:
            cx = (p.bbox[0] + p.bbox[2]) / 2
            cy = (p.bbox[1] + p.bbox[3]) / 2
            for rz in restricted:
                rx1, ry1, rx2, ry2 = rz
                if rx1 <= cx <= rx2 and ry1 <= cy <= ry2:
                    alerts.append(
                        {
                            "type": "zone_intrusion",
                            "person_id": p.person_id,
                            "zone": zone,
                            "restricted_area": list(rz),
                            "severity": "critical",
                        }
                    )
        return alerts

    def set_restricted_zones(
        self,
        zones: Dict[str, List[Tuple[int, int, int, int]]],
    ) -> None:
        """Set restricted zone boundaries per zone name."""
        self._restricted_zones = zones

    def reset_tracking(self, camera_id: str = "") -> None:
        """Reset tracking state for a camera (or all)."""
        if camera_id:
            self._track_state.pop(camera_id, None)
        else:
            self._track_state.clear()


# ── CLI entry ────────────────────────────────────────────────────

def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Staff behavior detector")
    parser.add_argument(
        "--frame", required=True, help="Path to image file"
    )
    parser.add_argument("--camera", default="", help="Camera ID")
    parser.add_argument("--zone", default="", help="Zone name")
    parser.add_argument(
        "--output", default="", help="Output JSON path (stdout if empty)"
    )
    parser.add_argument(
        "--model", default="", help="YOLO model path"
    )
    args = parser.parse_args()

    detector = StaffBehaviorDetector(
        model_path=args.model or None
    )
    result = detector.detect(
        args.frame,
        camera_id=args.camera,
        zone=args.zone,
    )

    output = {
        "frame_id": result.frame_id,
        "timestamp": result.timestamp,
        "store_id": result.store_id,
        "zone": result.zone,
        "camera_id": result.camera_id,
        "person_count": result.person_count,
        "ppe_compliance_rate": result.ppe_compliance_rate,
        "whispering_pairs": result.whispering_pairs,
        "loitering_count": result.loitering_count,
        "alerts": result.alerts,
        "persons": [
            {
                "person_id": p.person_id,
                "bbox": list(p.bbox),
                "confidence": round(p.confidence, 3),
                "ppe_hat": p.ppe_hat,
                "ppe_apron": p.ppe_apron,
                "dwell_sec": round(p.dwell_sec, 1),
                "is_loitering": p.is_loitering,
            }
            for p in result.persons
        ],
    }

    if args.output:
        with open(args.output, "w") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"Result written to {args.output}")
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
