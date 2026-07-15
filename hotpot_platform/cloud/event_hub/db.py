"""SQLite persistence for Event Hub (DEV-101, PG-compatible schema later)."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from hotpot_platform.cloud.event_hub.daily_report_store import SQLITE_DAILY_REPORTS_SCHEMA
from hotpot_platform.cloud.event_hub.iot_readings_store import SQLITE_IOT_READINGS_SCHEMA
from hotpot_platform.cloud.event_hub.receiving_store import SQLITE_RECEIVING_SCHEMA
from hotpot_platform.cloud.event_hub.sop_assign_store import SQLITE_SOP_ASSIGN_SCHEMA
from hotpot_platform.cloud.event_hub.task_store import SQLITE_TASKS_SCHEMA

MAX_EVENTS_PER_STORE = 500


def create_hub_database(
    db_path: Path,
    database_url: Optional[str] = None,
) -> Union["HubDatabase", Any]:
    """Factory: PostgreSQL when HOTPOT_DATABASE_URL set, else SQLite."""
    url = database_url or os.environ.get("HOTPOT_DATABASE_URL", "")
    if url:
        from hotpot_platform.cloud.event_hub.pg_db import PostgresHubDatabase

        return PostgresHubDatabase(url)
    return HubDatabase(db_path)


class HubDatabase:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS events (
                        event_id TEXT PRIMARY KEY,
                        store_id TEXT NOT NULL,
                        level TEXT,
                        source TEXT,
                        payload TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_events_store ON events(store_id, created_at DESC);

                    CREATE TABLE IF NOT EXISTS store_snapshots (
                        store_id TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (store_id, kind)
                    );

                    CREATE TABLE IF NOT EXISTS device_registry (
                        device_id TEXT PRIMARY KEY,
                        payload TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    """
                    + SQLITE_RECEIVING_SCHEMA
                    + SQLITE_SOP_ASSIGN_SCHEMA
                    + SQLITE_TASKS_SCHEMA
                    + SQLITE_IOT_READINGS_SCHEMA
                    + SQLITE_DAILY_REPORTS_SCHEMA
                )
                conn.commit()
            finally:
                conn.close()

    def persist_event(self, store_id: str, event: Dict[str, Any]) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO events(event_id, store_id, level, source, payload, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event["event_id"],
                        store_id,
                        event.get("level"),
                        event.get("source"),
                        json.dumps(event, ensure_ascii=False),
                        event.get("timestamp"),
                    ),
                )
                conn.execute(
                    """
                    DELETE FROM events WHERE event_id IN (
                        SELECT event_id FROM events WHERE store_id = ?
                        ORDER BY created_at DESC LIMIT -1 OFFSET ?
                    )
                    """,
                    (store_id, MAX_EVENTS_PER_STORE),
                )
                conn.commit()
            finally:
                conn.close()

    def persist_snapshot(self, store_id: str, kind: str, payload: Any) -> None:
        from datetime import datetime, timezone

        updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO store_snapshots(store_id, kind, payload, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (store_id, kind, json.dumps(payload, ensure_ascii=False), updated_at),
                )
                conn.commit()
            finally:
                conn.close()

    def update_devices(self, devices: Dict[str, Any]) -> None:
        from datetime import datetime, timezone

        updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM device_registry")
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO device_registry(device_id, payload, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    [
                        (device_id, json.dumps(payload, ensure_ascii=False), updated_at)
                        for device_id, payload in devices.items()
                    ],
                )
                conn.commit()
            finally:
                conn.close()

    def get_devices(self) -> Dict[str, Any]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute("SELECT device_id, payload FROM device_registry").fetchall()
                return {row["device_id"]: json.loads(row["payload"]) for row in rows}
            finally:
                conn.close()

    def load_store_into(self, hub: Any, store_id: str) -> None:
        store = hub.get_store(store_id)
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT payload FROM events WHERE store_id = ? ORDER BY created_at DESC LIMIT ?",
                    (store_id, MAX_EVENTS_PER_STORE),
                ).fetchall()
                events = [json.loads(r["payload"]) for r in rows]
                store.load_events_batch(events)

                snaps = conn.execute(
                    "SELECT kind, payload FROM store_snapshots WHERE store_id = ?",
                    (store_id,),
                ).fetchall()
                for row in snaps:
                    store.load_snapshot(row["kind"], json.loads(row["payload"]))
            finally:
                conn.close()

    def is_empty(self) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                n = conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"]
                return n == 0
            finally:
                conn.close()

    def hydrate_hub(self, hub: Any, store_ids: Optional[List[str]] = None) -> None:
        ids = store_ids or [s["store_id"] for s in hub.list_stores()]
        for sid in ids:
            self.load_store_into(hub, sid)

    def on_persist(self, store_id: str, kind: str, payload: Any) -> None:
        if kind == "event":
            self.persist_event(store_id, payload)
        else:
            self.persist_snapshot(store_id, kind, payload)

    def query_waste_count_stats(
        self, store_id: str, days: int = 7
    ) -> Dict[str, Any]:
        """查询最近 N 天的废料计数趋势。

        从 events 表中筛选 vlm_waste_estimate 事件，
        提取 payload.items[].count 和 payload.total_waste_count，
        按天聚合。

        Returns:
            {
                "store_id": str,
                "days": int,
                "daily": [
                    {
                        "date": "2026-07-10",
                        "total_count": 42,
                        "event_count": 5,
                        "items": [{"sku": "毛肚", "count": 12, "waste_type": "备餐废弃"}, ...]
                    },
                    ...
                ],
                "trend": [...],  # 每日 total_count 数组（用于前端折线图）
            }
        """
        from datetime import datetime, timedelta, timezone

        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).strftime("%Y-%m-%d")

        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT payload, created_at FROM events
                    WHERE store_id = ?
                      AND json_extract(payload, '$.event_type') = 'vlm_waste_estimate'
                      AND created_at >= ?
                    ORDER BY created_at DESC
                    """,
                    (store_id, cutoff),
                ).fetchall()

                # ── 按天聚合 ──
                daily_map: Dict[str, Dict[str, Any]] = {}
                for row in rows:
                    try:
                        payload = json.loads(row["payload"])
                    except (json.JSONDecodeError, TypeError):
                        continue

                    meta = payload.get("metadata", {})
                    items = meta.get("items", [])
                    total_count = meta.get("total_waste_count", 0)

                    # 如果顶层有 total_waste_count 直接用，否则从 items 累加
                    if not total_count:
                        for item in items:
                            c = item.get("count", 0)
                            if isinstance(c, (int, float)):
                                total_count += int(c)

                    # 日期键
                    date_key = row["created_at"][:10] if row["created_at"] else "unknown"

                    if date_key not in daily_map:
                        daily_map[date_key] = {
                            "date": date_key,
                            "total_count": 0,
                            "event_count": 0,
                            "items": [],
                        }

                    entry = daily_map[date_key]
                    entry["total_count"] += total_count
                    entry["event_count"] += 1

                    # 收集 item 级别的计数明细
                    for item in items:
                        sku = item.get("sku", "unknown")
                        count = item.get("count", 0)
                        if isinstance(count, (int, float)) and count > 0:
                            entry["items"].append({
                                "sku": sku,
                                "count": int(count),
                                "waste_type": item.get("waste_type", "备餐废弃"),
                            })
            finally:
                conn.close()

        # ── 排序 ──
        daily = sorted(daily_map.values(), key=lambda d: d["date"])

        # ── 填充缺失日期为 0（防止前端 trend 数组错位）──
        from datetime import date as date_type
        today = date_type.today()
        full_daily: list = []
        cursor = date_type.fromisoformat(cutoff) if cutoff else today - timedelta(days=days)
        while cursor <= today:
            date_key = cursor.isoformat()
            entry = daily_map.get(date_key)
            if entry:
                full_daily.append(entry)
            else:
                full_daily.append({
                    "date": date_key,
                    "total_count": 0,
                    "event_count": 0,
                    "items": [],
                })
            cursor += timedelta(days=1)
        daily = full_daily

        trend = [d["total_count"] for d in daily]
        dates = [d["date"] for d in daily]

        return {
            "store_id": store_id,
            "days": days,
            "daily": daily,
            "trend": trend,
            "dates": dates,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
