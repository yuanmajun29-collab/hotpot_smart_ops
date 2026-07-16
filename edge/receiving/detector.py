"""Receiving dock ingredient detection pipeline.

Uses shared YOLO detector from edge/common/detector/ to identify food ingredients
at the receiving entrance. Pushes results to Hub via POST /v1/receiving/checkin.

Classes mapped to food categories:
  0: background, 1: meat, 2: vegetable, 3: seafood,
  4: frozen, 5: seasoning, 6: dry_goods, 7: tofu,
  8: other_ingredient

Usage:
  PYTHONPATH=. python3 -m edge.receiving.detector --image demo/data/receiving_sample.jpg

Dev mode: set HOTPOT_DEV_MODE=1 to mock the YOLO detector.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import httpx  # type: ignore

logger = logging.getLogger("receiving.detector")

# ── Ingredient class mapping ──
INGREDIENT_CLASSES: Dict[int, str] = {
    0: "肉类",
    1: "蔬菜",
    2: "豆制品",
    3: "海鲜",
    4: "冻品",
    5: "调料",
    6: "干货",
    7: "其他",
}

# ── Hub config ──
HUB_URL = os.environ.get("HOTPOT_HUB_URL", "http://127.0.0.1:8098")
STORE_ID = os.environ.get("HOTPOT_STORE_ID", "store_yuhuan")
DEVICE_ID = os.environ.get("HOTPOT_DEVICE_ID", "jetson-receiving-01")
API_KEY = os.environ.get("HOTPOT_API_KEY", "demo-key")

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_yolo_detector():
    """Lazy-load the shared YOLO detector, falling back to mock in dev mode."""
    if os.environ.get("HOTPOT_DEV_MODE"):
        return _MockDetector()

    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from edge.common.detector.hotpot_detector import HotpotDetector
        detector = HotpotDetector(backend="yolo")
        detector.load()
        logger.info("YOLO detector loaded from edge/common/detector")
        return detector
    except Exception as e:
        logger.warning("Unable to load real detector (%s), using mock", e)
        return _MockDetector()


class _MockDetector:
    """Mock detector for dev/testing — returns synthetic ingredient detections."""

    def detect(self, image, zone: str = "receiving") -> Dict[str, Any]:
        import random
        h, w = image.shape[:2] if image is not None else (480, 640)
        detections = []
        # Generate 3-8 random ingredient detections
        for _ in range(random.randint(3, 8)):
            cls_id = random.randint(0, 7)
            detections.append({
                "class_id": cls_id,
                "class_name": INGREDIENT_CLASSES.get(cls_id, "未知"),
                "confidence": round(random.uniform(0.72, 0.98), 3),
                "bbox": [
                    random.randint(0, w // 2),
                    random.randint(0, h // 2),
                    random.randint(w // 4, w),
                    random.randint(h // 4, h),
                ],
                "area_pct": round(random.uniform(2, 18), 1),
            })

        # Aggregate by class
        agg: Dict[str, int] = {}
        for d in detections:
            agg[d["class_name"]] = agg.get(d["class_name"], 0) + 1

        return {
            "total_detections": len(detections),
            "detections": detections,
            "ingredients": [{"class": k, "count": v, "confidence": round(
                sum(d["confidence"] for d in detections if d["class_name"] == k) / max(v, 1), 3
            )} for k, v in agg.items()],
            "label_counts": agg,
        }


_detector = None


def get_detector():
    global _detector
    if _detector is None:
        _detector = _load_yolo_detector()
    return _detector


def detect_ingredients(image_path: Optional[str] = None, image: Optional[Any] = None) -> Dict[str, Any]:
    """Run YOLO detection on a receiving dock image.

    Returns:
        dict with keys: ingredients, total_items, image_ref, timestamp
    """
    if image_path:
        img = cv2.imread(image_path)
        if img is None:
            raise FileNotFoundError(f"Cannot read image: {image_path}")
    elif image is not None:
        img = image
    else:
        raise ValueError("Either image_path or image must be provided")

    detector = get_detector()
    result = detector.detect(img, zone="receiving")

    ingredients = result.get("ingredients", [])
    total_items = result.get("total_detections", 0)

    return {
        "ingredients": ingredients,
        "total_items": total_items,
        "image_ref": image_path or "",
        "timestamp": utc_now_iso(),
        "resolution": f"{img.shape[1]}x{img.shape[0]}",
    }


def push_to_hub(
    ingredients: List[Dict],
    weight_kg: Optional[float] = None,
    po_weight_kg: Optional[float] = None,
    temp_c: Optional[float] = None,
    batch_ref: Optional[str] = None,
    image_ref: str = "",
) -> Dict[str, Any]:
    """Push detection results to Hub POST /v1/receiving/checkin."""
    payload: Dict[str, Any] = {
        "store_id": STORE_ID,
        "device_id": DEVICE_ID,
        "ingredients": ingredients,
        "source": "edge_yolo_v2",
        "timestamp": utc_now_iso(),
    }
    if weight_kg is not None:
        payload["weight_kg"] = weight_kg
    if po_weight_kg is not None:
        payload["po_weight_kg"] = po_weight_kg
    if temp_c is not None:
        payload["temp_c"] = temp_c
    if batch_ref:
        payload["batch_ref"] = batch_ref
    if image_ref:
        payload["image_ref"] = image_ref

    try:
        resp = httpx.post(
            f"{HUB_URL}/v1/receiving/checkin",
            json=payload,
            headers={"X-Api-Key": API_KEY, "Content-Type": "application/json"},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info("checkin OK id=%s variance=%s%%",
                      data.get("checkin_id"), data.get("variance_pct", "N/A"))
        return data
    except Exception as e:
        logger.error("checkin failed: %s", e)
        return {"ok": False, "error": str(e)}


def run_once(image_path: str, **kwargs) -> Dict[str, Any]:
    """Full pipeline: detect → push. Returns combined result dict."""
    result = detect_ingredients(image_path=image_path)
    hub_resp = push_to_hub(
        ingredients=result["ingredients"],
        image_ref=result.get("image_ref", image_path),
        **kwargs,
    )
    return {**result, "hub_response": hub_resp}


# ── CLI ──
def main():
    parser = argparse.ArgumentParser(description="Receiving dock ingredient detection")
    parser.add_argument("--image", help="Path to input image")
    parser.add_argument("--weight-kg", type=float, default=None, help="Scale weight (kg)")
    parser.add_argument("--po-weight-kg", type=float, default=None, help="PO expected weight (kg)")
    parser.add_argument("--temp-c", type=float, default=None, help="Cold chain temperature (°C)")
    parser.add_argument("--batch-ref", help="PO batch reference")
    parser.add_argument("--no-push", action="store_true", help="Detect only, don't push to Hub")
    parser.add_argument("--json", action="store_true", help="Output JSON only")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if not args.image:
        parser.error("--image is required")

    # Detection
    result = detect_ingredients(image_path=args.image)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"\n{'='*50}")
        print(f"  进货口食材检测 — {STORE_ID}")
        print(f"{'='*50}")
        print(f"  检测项数: {result['total_items']}")
        print(f"  食材类别:")
        for ing in result["ingredients"]:
            print(f"    {ing['class']:8s} x{ing['count']:3d}  (置信度 {ing.get('confidence', 0):.2f})")
        print(f"  时间: {result['timestamp']}")
        print(f"  图片: {result['image_ref']}")

    # Push to Hub
    if not args.no_push:
        hub_resp = push_to_hub(
            ingredients=result["ingredients"],
            weight_kg=args.weight_kg,
            po_weight_kg=args.po_weight_kg,
            temp_c=args.temp_c,
            batch_ref=args.batch_ref,
            image_ref=result.get("image_ref", args.image),
        )
        if hub_resp.get("ok"):
            print(f"\n  ✓ Hub checkin: {hub_resp.get('checkin_id')}")
            if hub_resp.get("variance_pct") is not None:
                print(f"    重量偏差: {hub_resp['variance_pct']:+.1f}%")
        else:
            print(f"\n  ✗ Hub error: {hub_resp.get('error')}")


if __name__ == "__main__":
    main()
