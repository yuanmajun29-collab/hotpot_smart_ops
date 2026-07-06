"""POS integration bridge — mock/file/API → Event Hub (DEV-304)."""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from common.hub_client import EdgeHubClient

DEFAULT_POS_FILE = PROJECT_ROOT / "demo" / "data" / "pos_stats.json"


def utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_pos_file(path: Path, store_id: str, store_name: str) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["store_id"] = store_id
    data["store_name"] = store_name
    data["date"] = data.get("date") or utc_today()
    data["source"] = "file"
    data["synced_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return data


def simulate_live_stats(base: Dict[str, Any], store_id: str) -> Dict[str, Any]:
    """Apply small random drift to simulate live POS feed."""
    stats = dict(base)
    stats["store_id"] = store_id
    stats["date"] = utc_today()
    stats["source"] = "simulated"
    stats["synced_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    stats["turnover_rate"] = round(float(stats.get("turnover_rate", 2.5)) + random.uniform(-0.05, 0.08), 2)
    stats["daily_revenue"] = int(stats.get("daily_revenue", 48000) + random.randint(-800, 1200))
    stats["dish_timeout_count"] = max(0, int(stats.get("dish_timeout_count", 0)) + random.randint(-1, 1))
    stats["queue_count"] = max(0, int(stats.get("queue_count", 0)) + random.randint(-2, 3))
    stats["queue_lost_rate"] = round(max(0, float(stats.get("queue_lost_rate", 0.1)) + random.uniform(-0.02, 0.02)), 3)
    return stats


def fetch_pos_api(api_url: str, store_id: str, api_key: str = "") -> Dict[str, Any]:
    url = api_url.format(store_id=store_id) if "{store_id}" in api_url else api_url
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    data["store_id"] = store_id
    data["source"] = "api"
    data["synced_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return data


def sync_pos(
    store_id: str,
    hub_url: str,
    *,
    mode: str = "file",
    pos_file: Path = DEFAULT_POS_FILE,
    store_name: str = "",
    api_url: str = "",
    api_key: str = "",
    simulate: bool = True,
) -> Dict[str, Any]:
    if mode == "api" and api_url:
        stats = fetch_pos_api(api_url, store_id, api_key)
    else:
        seed_path = pos_file
        store_seed = PROJECT_ROOT / "demo" / "data" / "stores" / store_id / "seed.json"
        if store_seed.exists():
            seed = json.loads(store_seed.read_text(encoding="utf-8"))
            if seed.get("pos_stats"):
                stats = dict(seed["pos_stats"])
            else:
                stats = load_pos_file(seed_path, store_id, store_name)
        elif seed_path.exists():
            stats = load_pos_file(seed_path, store_id, store_name)
        else:
            stats = {
                "store_id": store_id,
                "store_name": store_name or store_id,
                "turnover_rate": 2.5,
                "daily_revenue": 48000,
                "avg_ticket": 120,
                "table_count": 40,
                "dish_timeout_count": 2,
                "queue_count": 10,
                "queue_lost_rate": 0.1,
            }
        if simulate and mode != "file":
            stats = simulate_live_stats(stats, store_id)
        stats["store_name"] = store_name or stats.get("store_name", store_id)

    client = EdgeHubClient(hub_url, store_id)
    client.post("/pos", stats)
    client.flush_queue()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="POS → Event Hub sync")
    parser.add_argument("--store-id", default="store_yuhuan")
    parser.add_argument("--store-name", default="")
    parser.add_argument("--hub-url", default="http://127.0.0.1:8088")
    parser.add_argument("--mode", choices=("file", "sim", "api"), default="sim")
    parser.add_argument("--pos-file", default=str(DEFAULT_POS_FILE))
    parser.add_argument("--api-url", default="", help="POS REST endpoint, supports {store_id}")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--interval", type=int, default=0, help="0=once, >0=periodic seconds")
    parser.add_argument("--cycles", type=int, default=0, help="0=forever when interval>0")
    args = parser.parse_args()

    names = {
        "store_yuhuan": "冯校长火锅·玉环店",
        "store_jiaojiang": "冯校长火锅·椒江店",
    }
    store_name = args.store_name or names.get(args.store_id, args.store_id)
    pos_file = Path(args.pos_file)

    def _once() -> None:
        stats = sync_pos(
            args.store_id,
            args.hub_url,
            mode=args.mode,
            pos_file=pos_file,
            store_name=store_name,
            api_url=args.api_url,
            api_key=args.api_key,
            simulate=args.mode == "sim",
        )
        print(json.dumps(stats, ensure_ascii=False, indent=2))

    if args.interval <= 0:
        _once()
        return

    cycle = 0
    try:
        while args.cycles == 0 or cycle < args.cycles:
            _once()
            cycle += 1
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("[pos_bridge] stopped")


if __name__ == "__main__":
    main()
