#!/usr/bin/env python3
"""Bridge: staff behavior detection → Event Hub.

Runs periodically on Jetson edge device:
  1. Captures frame from camera (or IPC frame)
  2. Runs StaffBehaviorDetector
  3. POSTs result to Hub /api/staff-behavior/event

Usage:
    python3 bridge.py --frame /tmp/latest.jpg --camera cam_staff_01 --zone kitchen
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

# ── Edge path injection ──────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from edge.staff_behavior.detector import StaffBehaviorDetector, DetectionResult

HUB_URL = os.environ.get("HOTPOT_HUB_URL", "http://192.168.2.85:8098")
STORE_ID = os.environ.get("HOTPOT_STORE_ID", "store_yuhuan")
INTERVAL_SEC = int(os.environ.get("STAFF_BRIDGE_INTERVAL_SEC", "5"))


def post_to_hub(result: DetectionResult, hub_url: str, timeout: int = 10) -> bool:
    """POST detection result to Event Hub."""
    payload = {
        "event_id": f"staff-{result.frame_id}",
        "store_id": result.store_id,
        "level": "warning" if result.alerts else "info",
        "source": f"staff_behavior/{result.camera_id}",
        "event_type": "staff_behavior",
        "timestamp": result.timestamp,
        "message": (
            f"Staff detection: {result.person_count} person(s), "
            f"PPE {result.ppe_compliance_rate}%, "
            f"{result.whispering_pairs} whisper pairs, "
            f"{result.loitering_count} loitering"
        ),
        "metadata": {
            "camera_id": result.camera_id,
            "zone": result.zone,
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
        },
    }

    try:
        resp = requests.post(
            f"{hub_url.rstrip('/')}/api/staff-behavior/event",
            json=payload,
            timeout=timeout,
        )
        if resp.status_code < 300:
            print(
                f"[{datetime.now().isoformat()}] POST OK: {result.person_count}p, "
                f"PPE {result.ppe_compliance_rate}%"
            )
            return True
        else:
            print(
                f"[{datetime.now().isoformat()}] POST FAIL {resp.status_code}: "
                f"{resp.text[:200]}"
            )
            return False
    except requests.exceptions.RequestException as e:
        print(f"[{datetime.now().isoformat()}] POST ERROR: {e}")
        return False


def run_loop(
    detector: StaffBehaviorDetector,
    hub_url: str,
    camera_id: str,
    zone: str,
    frame_provider,
    interval: int = 5,
) -> None:
    """Main loop: capture → detect → post, every N seconds."""
    print(
        f"[{datetime.now().isoformat()}] Staff behavior bridge starting. "
        f"Hub: {hub_url}, Camera: {camera_id}, Zone: {zone}, Interval: {interval}s"
    )

    while True:
        try:
            frame = frame_provider()
            if frame is None:
                time.sleep(1)
                continue

            result = detector.detect(frame, camera_id=camera_id, zone=zone)
            post_to_hub(result, hub_url)

            time.sleep(interval)
        except KeyboardInterrupt:
            print("Interrupted, exiting.")
            break
        except Exception:
            traceback.print_exc()
            time.sleep(interval)


def file_frame_provider(frame_path: str):
    """Frame provider that reads from a file (IPC/RTSP static)."""
    import cv2

    img = cv2.imread(frame_path)
    return img


def main():
    parser = argparse.ArgumentParser(
        description="Staff behavior bridge to Event Hub"
    )
    parser.add_argument(
        "--frame", required=True, help="Image file path (or IPC frame path)"
    )
    parser.add_argument("--camera", default="cam_staff_01", help="Camera ID")
    parser.add_argument("--zone", default="kitchen", help="Zone name")
    parser.add_argument(
        "--hub", default=HUB_URL, help="Event Hub URL"
    )
    parser.add_argument(
        "--interval", type=int, default=INTERVAL_SEC, help="Loop interval (sec)"
    )
    parser.add_argument(
        "--once", action="store_true", help="Run once and exit"
    )
    parser.add_argument(
        "--model", default="", help="YOLO model path"
    )
    parser.add_argument(
        "--output", default="", help="Output JSON path (for --once mode)"
    )
    args = parser.parse_args()

    detector = StaffBehaviorDetector(model_path=args.model or None)

    if args.once:
        import cv2

        frame = cv2.imread(args.frame)
        if frame is None:
            print(f"ERROR: Cannot read frame: {args.frame}")
            sys.exit(1)

        result = detector.detect(
            frame, camera_id=args.camera, zone=args.zone
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
        }

        if args.output:
            with open(args.output, "w") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)
        else:
            print(json.dumps(output, ensure_ascii=False, indent=2))

        post_to_hub(result, args.hub)
    else:
        run_loop(
            detector,
            hub_url=args.hub,
            camera_id=args.camera,
            zone=args.zone,
            frame_provider=lambda: file_frame_provider(args.frame),
            interval=args.interval,
        )


if __name__ == "__main__":
    main()
