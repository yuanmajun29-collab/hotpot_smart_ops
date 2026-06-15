"""Load per-store UAT edge configuration and ROI tables."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UAT_ROOT = PROJECT_ROOT / "deploy" / "uat"

# Demo file mapping when stream_mode=file (no real RTSP)
DEFAULT_FILE_SOURCES = {
    "front": PROJECT_ROOT / "demo" / "data" / "front_hall.jpg",
    "kitchen": PROJECT_ROOT / "demo" / "data" / "kitchen.jpg",
}


def uat_dir(store_id: str, uat_root: Path = DEFAULT_UAT_ROOT) -> Path:
    return uat_root / store_id


def load_store_config(store_id: str, uat_root: Path = DEFAULT_UAT_ROOT) -> Dict[str, Any]:
    path = uat_dir(store_id, uat_root) / "config.json"
    if not path.exists():
        raise FileNotFoundError(f"Store config not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_roi_tables(store_id: str, uat_root: Path = DEFAULT_UAT_ROOT) -> Dict[str, Any]:
    path = uat_dir(store_id, uat_root) / "roi_tables.json"
    if not path.exists():
        return {"store_id": store_id, "image_size": [1920, 1080], "tables": []}
    return json.loads(path.read_text(encoding="utf-8"))


def scale_bbox(bbox: List[int], src_size: Tuple[int, int], dst_size: Tuple[int, int]) -> List[int]:
    sw, sh = src_size
    dw, dh = dst_size
    if sw <= 0 or sh <= 0:
        return bbox
    sx, sy = dw / sw, dh / sh
    x1, y1, x2, y2 = bbox
    return [int(x1 * sx), int(y1 * sy), int(x2 * sx), int(y2 * sy)]


def table_regions_for_frame(
    store_id: str,
    frame_width: int,
    frame_height: int,
    uat_root: Path = DEFAULT_UAT_ROOT,
) -> List[Dict[str, Any]]:
    roi = load_roi_tables(store_id, uat_root)
    src_w, src_h = roi.get("image_size", [1920, 1080])
    regions: List[Dict[str, Any]] = []
    for t in roi.get("tables", []):
        bbox = scale_bbox(t["bbox"], (src_w, src_h), (frame_width, frame_height))
        regions.append({"table_id": t["table_id"], "bbox": bbox})
    return regions


def camera_file_source(camera: Dict[str, Any], zone: str) -> Path:
    if camera.get("file_source"):
        return Path(camera["file_source"])
    return DEFAULT_FILE_SOURCES.get(zone, DEFAULT_FILE_SOURCES["front"])


def get_stream_mode(camera: Dict[str, Any]) -> str:
    """file | rtsp — PoC 默认 file，不接真实摄像头。"""
    return camera.get("stream_mode", "file")
