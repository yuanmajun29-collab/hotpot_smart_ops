"""POS integration bridge — mock/file/API → Event Hub (DEV-304).

⚠️ 改造方案要求 (P0-D):
   - 默认禁止生产模拟数据
   - 新增真实 POS API/文件适配、鉴权、checkpoint、重试与死信
   - 生产环境必须使用 file 或 api 模式，sim 模式仅限开发测试
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# integrations/ → cloud/ → hotpot_platform/ → repository root.
# The shared ``common`` package lives at repository root, not under
# ``hotpot_platform``.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
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


# ============================================================
# v5.0 数据引擎扩展 — per-SKU 日销量
# ============================================================

DEFAULT_SKU_SALES_FILE = PROJECT_ROOT / "demo" / "data" / "sku_sales_daily.json"


def load_sku_sales_csv(csv_path: Path, store_id: str) -> List[Dict[str, Any]]:
    """Load historical per-SKU sales without changing business dates."""
    records: List[Dict[str, Any]] = []
    with csv_path.open(newline="", encoding="utf-8-sig") as source:
        for line_number, row in enumerate(csv.DictReader(source), start=2):
            business_date = (row.get("business_date") or row.get("date") or "").strip()
            if not business_date:
                raise ValueError(f"missing business_date/date in {csv_path.name} line {line_number}")
            sku = (row.get("sku") or row.get("sku_code") or "").strip()
            sku_name = (row.get("sku_name") or row.get("name") or sku).strip()
            if not sku:
                raise ValueError(f"missing sku/sku_code in {csv_path.name} line {line_number}")
            try:
                qty_sold = float(row.get("qty_sold") or row.get("quantity") or 0)
                unit_price = float(row.get("unit_price") or row.get("price") or 0)
            except ValueError as exc:
                raise ValueError(f"invalid numeric value in {csv_path.name} line {line_number}") from exc
            revenue_raw = row.get("revenue") or row.get("amount")
            try:
                revenue = float(revenue_raw) if revenue_raw not in (None, "") else qty_sold * unit_price
            except ValueError as exc:
                raise ValueError(f"invalid revenue in {csv_path.name} line {line_number}") from exc
            records.append({
                "store_id": row.get("store_id") or store_id,
                "business_date": business_date,
                "sku": sku,
                "sku_name": sku_name,
                "category": row.get("category", ""),
                "qty_sold": qty_sold,
                "unit": row.get("unit") or "份",
                "unit_price": unit_price,
                "revenue": revenue,
                "source": "pos_csv",
            })
    return records


def fetch_sku_sales(
    store_id: str,
    date: str = "",
    *,
    mode: str = "file",
    sku_file: Path = DEFAULT_SKU_SALES_FILE,
    csv_file: Optional[Path] = None,
    api_url: str = "",
    api_key: str = "",
) -> List[Dict[str, Any]]:
    """获取 per-SKU 日销量明细 (数据引擎 N01 输入)。

    Returns:
        [{store_id, business_date, sku, sku_name, category, qty_sold, unit, unit_price, revenue, hour_dist}]
    """
    target_date = date or utc_today()

    if mode == "csv":
        if not csv_file or not csv_file.exists():
            raise FileNotFoundError("mode=csv requires an existing csv_file")
        records = load_sku_sales_csv(csv_file, store_id)
        if date:
            records = [r for r in records if r["business_date"] == date]
    elif mode == "api" and api_url:
        url = api_url.format(store_id=store_id, date=target_date)
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        records = data if isinstance(data, list) else data.get("items", data.get("sales", []))
    elif sku_file.exists():
        data = json.loads(sku_file.read_text(encoding="utf-8"))
        # 支持两种格式: [{...}] 或 {date: [{...}]}
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            records = data.get(target_date, data.get(list(data.keys())[0], []))
        else:
            records = []
    else:
        # 无数据时返回 mock 结构
        records = _mock_sku_sales(store_id, target_date)

    synced_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for r in records:
        r["store_id"] = r.get("store_id", store_id)
        r["business_date"] = r.get("business_date", target_date)
        r["source"] = r.get("source", mode)
        r.setdefault("unit", "份")
        r.setdefault("qty_sold", 0)
        r["synced_at"] = synced_at
    return records


def _mock_sku_sales(store_id: str, date: str) -> List[Dict[str, Any]]:
    """生成演示 per-SKU 销量数据 (用于开发/演示)。"""
    return [
        {"store_id": store_id, "business_date": date, "sku": "毛肚", "sku_name": "鲜毛肚",
         "category": "荤菜", "qty_sold": 48, "unit": "份", "unit_price": 68, "revenue": 3264},
        {"store_id": store_id, "business_date": date, "sku": "鸭肠", "sku_name": "生抠鸭肠",
         "category": "荤菜", "qty_sold": 35, "unit": "份", "unit_price": 38, "revenue": 1330},
        {"store_id": store_id, "business_date": date, "sku": "牛肉", "sku_name": "精品肥牛",
         "category": "荤菜", "qty_sold": 55, "unit": "份", "unit_price": 58, "revenue": 3190},
        {"store_id": store_id, "business_date": date, "sku": "虾滑", "sku_name": "手打虾滑",
         "category": "荤菜", "qty_sold": 30, "unit": "份", "unit_price": 42, "revenue": 1260},
        {"store_id": store_id, "business_date": date, "sku": "藕片", "sku_name": "鲜藕片",
         "category": "素菜", "qty_sold": 40, "unit": "份", "unit_price": 18, "revenue": 720},
        {"store_id": store_id, "business_date": date, "sku": "土豆", "sku_name": "功夫土豆片",
         "category": "素菜", "qty_sold": 52, "unit": "份", "unit_price": 16, "revenue": 832},
        {"store_id": store_id, "business_date": date, "sku": "锅底红汤", "sku_name": "经典红汤锅底",
         "category": "锅底", "qty_sold": 60, "unit": "锅", "unit_price": 58, "revenue": 3480},
        {"store_id": store_id, "business_date": date, "sku": "啤酒", "sku_name": "雪花纯生",
         "category": "酒水", "qty_sold": 80, "unit": "瓶", "unit_price": 12, "revenue": 960},
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="POS → Event Hub sync")
    parser.add_argument("--store-id", default="store_yuhuan")
    parser.add_argument("--store-name", default="")
    parser.add_argument("--hub-url", default="http://127.0.0.1:8088")
    parser.add_argument("--mode", choices=("file", "sim", "api"), default="file")  # ⚠️ 改造方案: 默认改为file，禁止生产sim
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

    # ⚠️ 生产环境安全检查: sim模式仅限开发测试
    if args.mode == "sim":
        import os
        env = os.environ.get("HOTPOT_ENV", "").lower()
        if env in ("production", "prod", "uat"):
            print("[POS Bridge] ⚠️ 警告: 生产环境禁止使用sim模拟模式!")
            print("[POS Bridge] 请使用 --mode file 或 --mode api 连接真实POS数据源")
            return
        else:
            print("[POS Bridge] ℹ️ 开发/演示模式: 使用sim模拟数据 (非生产环境)")

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
