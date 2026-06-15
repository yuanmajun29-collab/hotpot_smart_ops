#!/usr/bin/env python3
"""
Build table-state training dataset from annotated front-hall images (DEV-201/202).

Crops each table ROI from source images into class folders for YOLO classification training.

Usage:
  python3 scripts/build_table_dataset.py --store-id store_yuhuan --label empty
  python3 scripts/build_table_dataset.py --store-id store_yuhuan --auto-label mock

Output layout (YOLO classify format):
  datasets/table_state/{empty,dining,need_clean,checkout}/*.jpg
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.store_config import DEFAULT_UAT_ROOT, table_regions_for_frame

DEFAULT_IMAGE = PROJECT_ROOT / "demo" / "data" / "front_hall.jpg"
OUTPUT_ROOT = PROJECT_ROOT / "datasets" / "table_state"


def crop_tables(
    image_path: Path,
    store_id: str,
    label: str,
    uat_root: Path,
    output_root: Path,
) -> int:
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(image_path)
    h, w = image.shape[:2]
    regions = table_regions_for_frame(store_id, w, h, uat_root)
    out_dir = output_root / label
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for region in regions:
        x1, y1, x2, y2 = region["bbox"]
        roi = image[y1:y2, x1:x2]
        if roi.size == 0:
            continue
        fname = f"{store_id}_{region['table_id']}_{image_path.stem}.jpg"
        cv2.imwrite(str(out_dir / fname), roi)
        count += 1
    return count


def auto_label_mock(image_path: Path, store_id: str, uat_root: Path, output_root: Path) -> int:
    from edge.detector.hotpot_detector import MockHotpotDetector

    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(image_path)
    h, w = image.shape[:2]
    regions = table_regions_for_frame(store_id, w, h, uat_root)
    det = MockHotpotDetector(store_id)
    states = det.detect_tables(image, regions)
    total = 0
    for ts, region in zip(states, regions):
        x1, y1, x2, y2 = region["bbox"]
        roi = image[y1:y2, x1:x2]
        if roi.size == 0:
            continue
        out_dir = output_root / ts.state
        out_dir.mkdir(parents=True, exist_ok=True)
        fname = f"{store_id}_{ts.table_id}_{image_path.stem}.jpg"
        cv2.imwrite(str(out_dir / fname), roi)
        total += 1
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Build table state training crops")
    parser.add_argument("--store-id", default="store_yuhuan")
    parser.add_argument("--image", default=str(DEFAULT_IMAGE))
    parser.add_argument("--label", default="", help="Fixed label for all ROIs")
    parser.add_argument("--auto-label", choices=("mock", ""), default="")
    parser.add_argument("--output", default=str(OUTPUT_ROOT))
    parser.add_argument("--uat-root", default=str(DEFAULT_UAT_ROOT))
    args = parser.parse_args()

    image_path = Path(args.image)
    output_root = Path(args.output)
    uat_root = Path(args.uat_root)

    if args.auto_label == "mock":
        n = auto_label_mock(image_path, args.store_id, uat_root, output_root)
    elif args.label:
        n = crop_tables(image_path, args.store_id, args.label, uat_root, output_root)
    else:
        print("Specify --label <state> or --auto-label mock")
        sys.exit(1)

    manifest = {
        "store_id": args.store_id,
        "image": str(image_path),
        "output": str(output_root),
        "crops": n,
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Wrote {n} crops to {output_root}")


if __name__ == "__main__":
    main()
