#!/usr/bin/env python3
"""CLI tool to view/update per-store table ROI (DEV-203)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.store_config import DEFAULT_UAT_ROOT, load_roi_tables, uat_dir


def roi_path(store_id: str, uat_root: Path) -> Path:
    return uat_dir(store_id, uat_root) / "roi_tables.json"


def save_roi(store_id: str, data: Dict[str, Any], uat_root: Path) -> None:
    path = roi_path(store_id, uat_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Saved {path}")


def list_tables(store_id: str, uat_root: Path) -> None:
    roi = load_roi_tables(store_id, uat_root)
    print(f"Store: {store_id}")
    print(f"Image size: {roi.get('image_size')}")
    for t in roi.get("tables", []):
        print(f"  {t['table_id']}: bbox={t['bbox']}")


def set_table(store_id: str, table_id: str, bbox: List[int], uat_root: Path) -> None:
    roi = load_roi_tables(store_id, uat_root)
    roi.setdefault("store_id", store_id)
    tables = roi.setdefault("tables", [])
    updated = False
    for t in tables:
        if t["table_id"] == table_id:
            t["bbox"] = bbox
            updated = True
            break
    if not updated:
        tables.append({"table_id": table_id, "bbox": bbox})
    save_roi(store_id, roi, uat_root)


def generate_grid(store_id: str, cols: int, rows: int, width: int, height: int, uat_root: Path) -> None:
    tables: List[Dict[str, Any]] = []
    for r in range(rows):
        for c in range(cols):
            tid = f"T{r * cols + c + 1:02d}"
            x1 = int(c * width / cols + width * 0.02)
            y1 = int(r * height / rows + height * 0.05)
            x2 = int((c + 1) * width / cols - width * 0.02)
            y2 = int((r + 1) * height / rows - height * 0.05)
            tables.append({"table_id": tid, "bbox": [x1, y1, x2, y2]})
    data = {"store_id": store_id, "image_size": [width, height], "tables": tables}
    save_roi(store_id, data, uat_root)
    print(f"[OK] Generated {len(tables)} table ROIs ({cols}x{rows})")


def parse_bbox(s: str) -> List[int]:
    parts = [int(x.strip()) for x in s.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must be x1,y1,x2,y2")
    return parts


def main() -> None:
    parser = argparse.ArgumentParser(description="Table ROI calibration CLI")
    parser.add_argument("--store-id", required=True)
    parser.add_argument("--uat-root", default=str(DEFAULT_UAT_ROOT))
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List current ROI tables")

    p_set = sub.add_parser("set", help="Set bbox for one table")
    p_set.add_argument("--table", required=True)
    p_set.add_argument("--bbox", required=True, help="x1,y1,x2,y2")

    p_gen = sub.add_parser("generate", help="Generate grid ROIs")
    p_gen.add_argument("--cols", type=int, default=4)
    p_gen.add_argument("--rows", type=int, default=2)
    p_gen.add_argument("--width", type=int, default=1920)
    p_gen.add_argument("--height", type=int, default=1080)

    args = parser.parse_args()
    uat_root = Path(args.uat_root)

    if args.cmd == "list":
        list_tables(args.store_id, uat_root)
    elif args.cmd == "set":
        set_table(args.store_id, args.table, parse_bbox(args.bbox), uat_root)
    elif args.cmd == "generate":
        generate_grid(args.store_id, args.cols, args.rows, args.width, args.height, uat_root)


if __name__ == "__main__":
    main()
