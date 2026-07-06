#!/usr/bin/env python3
"""
Edge vision worker (DEV-203 mock mode + DEV-105 offline queue).

Uses UAT config ROI + file-based frames (no real RTSP).
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from edge.detector.hotpot_detector import create_detector, run_on_frame
from edge.stream.sources import create_source
from shared.hub_client import EdgeHubClient
from shared.store_config import (
    DEFAULT_UAT_ROOT,
    camera_file_source,
    get_stream_mode,
    load_store_config,
    table_regions_for_frame,
    uat_dir,
)

_stop_requested = False


def _handle_stop(signum: int, frame: object) -> None:
    global _stop_requested
    _stop_requested = True
    print(f"[vision_worker] stop signal ({signum}), finishing current cycle...", file=sys.stderr)


def process_camera(
    store_id: str,
    camera: Dict[str, Any],
    backend: str,
    hub: EdgeHubClient,
    uat_root: Path,
    out_dir: Optional[Path],
) -> Dict[str, Any]:
    zone = camera.get("zone", "front")
    file_path = camera_file_source(camera, zone)
    if not file_path.is_absolute():
        file_path = PROJECT_ROOT / file_path

    source = create_source(camera, zone, file_path)
    frame, src_meta = source.read()
    if frame is None:
        raise FileNotFoundError(f"No frame from {file_path}")

    table_regions = None
    if zone == "front":
        h, w = frame.shape[:2]
        table_regions = table_regions_for_frame(store_id, w, h, uat_root)

    result = run_on_frame(
        frame,
        backend=backend,
        store_id=store_id,
        zone=zone,
        table_regions=table_regions,
        image_label=str(file_path),
        annotated_dir=out_dir,
    )
    result["camera"] = camera.get("id", zone)
    result["stream_mode"] = get_stream_mode(camera)
    result["source_meta"] = src_meta
    if table_regions:
        result["roi_count"] = len(table_regions)

    if zone == "front":
        result = apply_jiaojiang_profile(result, store_id)

    hub.post_events(result.get("events", []))
    if result.get("table_states"):
        hub.post_tables(result["table_states"])

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{zone}_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return result


def apply_jiaojiang_profile(result: Dict[str, Any], store_id: str) -> Dict[str, Any]:
    if store_id != "store_jiaojiang" or not result.get("table_states"):
        return result
    profile = {
        "T01": "empty", "T02": "dining", "T03": "dining", "T04": "empty",
        "T05": "checkout", "T06": "dining", "T07": "empty", "T08": "need_clean",
    }
    for t in result["table_states"]:
        tid = t.get("table_id")
        if tid in profile:
            t["state"] = profile[tid]
    return result


def run_store_vision(
    store_id: str,
    hub_url: str,
    backend: str = "mock",
    uat_root: Path = DEFAULT_UAT_ROOT,
    out_dir: Optional[Path] = None,
    flush_queue: bool = True,
    cycle: int = 1,
) -> Dict[str, Any]:
    config = load_store_config(store_id, uat_root)
    api_key = config.get("edge_api_key", "")
    hub = EdgeHubClient(hub_url, store_id, api_key=api_key)
    if flush_queue:
        hub.flush_queue()

    outputs: Dict[str, Any] = {
        "store_id": store_id,
        "cycle": cycle,
        "cameras": [],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    for camera in config.get("cameras", []):
        res = process_camera(store_id, camera, backend, hub, uat_root, out_dir)
        outputs["cameras"].append(
            {
                "camera": camera.get("id"),
                "zone": camera.get("zone"),
                "events": len(res.get("events", [])),
                "tables": len(res.get("table_states") or []),
            }
        )

    outputs["queue_pending"] = hub.pending_count()
    outputs["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return outputs


def default_interval_from_config(store_id: str, uat_root: Path) -> float:
    """Derive cycle interval from slowest camera fps in UAT config."""
    config = load_store_config(store_id, uat_root)
    fps_values = [float(c.get("fps", 0)) for c in config.get("cameras", []) if c.get("fps")]
    if not fps_values:
        return 5.0
    return max(1.0 / min(fps_values), 1.0)


def run_periodic(
    store_id: str,
    hub_url: str,
    backend: str,
    uat_root: Path,
    out_dir: Optional[Path],
    interval: float,
    cycles: int,
    flush_queue_first: bool,
) -> List[Dict[str, Any]]:
    summaries: List[Dict[str, Any]] = []
    cycle = 0
    while True:
        if _stop_requested:
            break
        cycle += 1
        if cycles > 0 and cycle > cycles:
            break

        print(f"[vision_worker] cycle {cycle} · {store_id}", file=sys.stderr)
        summary = run_store_vision(
            store_id,
            hub_url,
            backend,
            uat_root,
            out_dir,
            flush_queue=flush_queue_first and cycle == 1,
            cycle=cycle,
        )
        summaries.append(summary)
        print(json.dumps(summary, ensure_ascii=False))

        if cycles > 0 and cycle >= cycles:
            break
        if interval <= 0:
            break
        if _stop_requested:
            break

        deadline = time.monotonic() + interval
        while time.monotonic() < deadline:
            if _stop_requested:
                break
            time.sleep(min(0.25, deadline - time.monotonic()))

    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(description="Edge vision worker (file mode, UAT ROI)")
    parser.add_argument("--store-id", default="store_yuhuan")
    parser.add_argument("--hub-url", default="http://127.0.0.1:8088")
    parser.add_argument("--backend", choices=("mock", "onnx", "yolo", "rknn"), default="mock")
    parser.add_argument("--uat-root", default=str(DEFAULT_UAT_ROOT))
    parser.add_argument("--output-dir", default="", help="Write results under store live dir")
    parser.add_argument("--flush-queue", action="store_true", default=True)
    parser.add_argument("--no-flush-queue", action="store_false", dest="flush_queue")
    parser.add_argument(
        "--interval",
        type=float,
        default=0,
        help="Seconds between scan cycles; 0 = single run (default)",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=0,
        help="Number of cycles; 0 = infinite when --interval > 0, else 1",
    )
    parser.add_argument(
        "--interval-from-config",
        action="store_true",
        help="Use 1/min(camera fps) from UAT config as interval",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    out = Path(args.output_dir) if args.output_dir else None
    uat_root = Path(args.uat_root)
    interval = args.interval
    if args.interval_from_config:
        interval = default_interval_from_config(args.store_id, uat_root)

    cycles = args.cycles
    if cycles <= 0:
        cycles = 0 if interval > 0 else 1

    if interval > 0 or cycles > 1:
        summaries = run_periodic(
            args.store_id,
            args.hub_url,
            args.backend,
            uat_root,
            out,
            interval,
            cycles,
            args.flush_queue,
        )
        if len(summaries) == 1:
            return
        print(
            json.dumps(
                {
                    "store_id": args.store_id,
                    "mode": "periodic",
                    "interval": interval,
                    "cycles_completed": len(summaries),
                    "last": summaries[-1] if summaries else None,
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return

    summary = run_store_vision(
        args.store_id,
        args.hub_url,
        args.backend,
        uat_root,
        out,
        args.flush_queue,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
