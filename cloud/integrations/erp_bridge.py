"""ERP / supply chain PO integration (DEV-305)."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.hub_client import EdgeHubClient
from shared.schemas import EventLevel, EventSource, utc_now_iso

DEFAULT_ERP_FILE = PROJECT_ROOT / "demo" / "data" / "erp_po_orders.json"
DEFAULT_RECEIVING = PROJECT_ROOT / "demo" / "data" / "incoming_materials.json"


def fetch_po_orders(
    store_id: str,
    *,
    mode: str = "file",
    erp_file: Path = DEFAULT_ERP_FILE,
    api_url: str = "",
    api_key: str = "",
) -> List[Dict[str, Any]]:
    if mode == "api" and api_url:
        url = api_url.format(store_id=store_id) if "{store_id}" in api_url else api_url
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        orders = data if isinstance(data, list) else data.get("orders", data.get("items", []))
    else:
        if not erp_file.exists():
            return []
        orders = json.loads(erp_file.read_text(encoding="utf-8"))
    return [o for o in orders if o.get("store_id", store_id) == store_id or not o.get("store_id")]


def po_to_receiving_record(po: Dict[str, Any], actuals: Optional[Dict[str, Dict]] = None) -> Dict[str, Any]:
    """Map ERP PO line to incoming_materials format for cost analyzer."""
    batch_id = po.get("batch_id") or po.get("po_id", "")
    actual = (actuals or {}).get(batch_id, {})
    planned = float(po.get("planned_qty_kg", po.get("po_qty_kg", 0)))
    actual_qty = float(actual.get("actual_qty_kg", planned * 0.97))
    unit_price = float(po.get("unit_price", po.get("po_unit_price", 0)))
    actual_price = float(actual.get("actual_unit_price", unit_price))
    usable = float(actual.get("usable_qty_kg", actual_qty * 0.9))
    return {
        "batch_id": batch_id,
        "po_id": po.get("po_id", ""),
        "sku": po.get("sku", ""),
        "supplier": po.get("supplier", ""),
        "po_qty_kg": planned,
        "actual_qty_kg": actual_qty,
        "po_unit_price": unit_price,
        "actual_unit_price": actual_price,
        "usable_qty_kg": usable,
        "quality_grade": actual.get("quality_grade", "A"),
        "remaining_shelf_days": actual.get("remaining_shelf_days", 3),
        "erp_status": po.get("status", "open"),
    }


def merge_with_actuals(orders: List[Dict[str, Any]], receiving_path: Path) -> List[Dict[str, Any]]:
    actuals: Dict[str, Dict] = {}
    if receiving_path.exists():
        for rec in json.loads(receiving_path.read_text(encoding="utf-8")):
            actuals[rec.get("batch_id", "")] = rec
    return [po_to_receiving_record(po, actuals) for po in orders]


def sync_erp(
    store_id: str,
    hub_url: str,
    *,
    mode: str = "file",
    erp_file: Path = DEFAULT_ERP_FILE,
    receiving_file: Path = DEFAULT_RECEIVING,
    api_url: str = "",
    api_key: str = "",
    output_file: Optional[Path] = None,
) -> Dict[str, Any]:
    orders = fetch_po_orders(store_id, mode=mode, erp_file=erp_file, api_url=api_url, api_key=api_key)
    records = merge_with_actuals(orders, receiving_file)

    payload = {
        "store_id": store_id,
        "synced_at": utc_now_iso(),
        "source": mode,
        "order_count": len(orders),
        "batch_count": len(records),
        "orders": orders,
        "receiving_records": records,
    }

    client = EdgeHubClient(hub_url, store_id)
    client.post("/erp", payload)

    for rec in records:
        if rec.get("erp_status") == "cancelled":
            continue
        po_qty = rec.get("po_qty_kg", 0)
        actual_qty = rec.get("actual_qty_kg", 0)
        if po_qty and abs(actual_qty - po_qty) / po_qty > 0.03:
            client.post_event(
                {
                    "event_type": "erp_po_variance",
                    "source": EventSource.SYSTEM.value,
                    "level": EventLevel.WARN.value,
                    "store_id": store_id,
                    "zone": "kitchen",
                    "message": f"ERP PO 偏差: {rec['sku']} 计划 {po_qty}kg 实收 {actual_qty}kg",
                    "metadata": {"batch_id": rec["batch_id"], "po_id": rec.get("po_id")},
                }
            )
    client.flush_queue()

    if output_file:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="ERP PO → Event Hub sync")
    parser.add_argument("--store-id", default="store_yuhuan")
    parser.add_argument("--hub-url", default="http://127.0.0.1:8088")
    parser.add_argument("--mode", choices=("file", "api"), default="file")
    parser.add_argument("--erp-file", default=str(DEFAULT_ERP_FILE))
    parser.add_argument("--receiving-file", default=str(DEFAULT_RECEIVING))
    parser.add_argument("--api-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--output", default="", help="Write merged receiving_records JSON")
    parser.add_argument("--interval", type=int, default=0)
    args = parser.parse_args()

    out = Path(args.output) if args.output else None

    def _once() -> None:
        result = sync_erp(
            args.store_id,
            args.hub_url,
            mode=args.mode,
            erp_file=Path(args.erp_file),
            receiving_file=Path(args.receiving_file),
            api_url=args.api_url,
            api_key=args.api_key,
            output_file=out,
        )
        print(json.dumps({k: result[k] for k in ("store_id", "order_count", "batch_count", "source")}, ensure_ascii=False))

    if args.interval <= 0:
        _once()
    else:
        try:
            while True:
                _once()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("[erp_bridge] stopped")


if __name__ == "__main__":
    main()
