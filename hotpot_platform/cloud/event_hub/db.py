"""SQLite persistence for Event Hub (DEV-101, PG-compatible schema later)."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from hotpot_platform.cloud.event_hub.daily_report_store import SQLITE_DAILY_REPORTS_SCHEMA
from hotpot_platform.cloud.event_hub.domain.waste_timeseries import (
    aggregate_waste_events,
    check_alert,
    compute_trend_comparison,
    format_alert_message,
)
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
                    + """
                    CREATE TABLE IF NOT EXISTS waste_timeseries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        store_id TEXT NOT NULL,
                        date TEXT NOT NULL,
                        total_count INTEGER NOT NULL DEFAULT 0,
                        event_count INTEGER NOT NULL DEFAULT 0,
                        top_skus TEXT NOT NULL DEFAULT '[]',
                        generated_at TEXT NOT NULL,
                        UNIQUE(store_id, date)
                    );
                    CREATE INDEX IF NOT EXISTS idx_wts_store_date
                        ON waste_timeseries(store_id, date DESC);

                    CREATE TABLE IF NOT EXISTS waste_alerts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        store_id TEXT NOT NULL,
                        date TEXT NOT NULL,
                        alert_type TEXT NOT NULL DEFAULT 'spike',
                        current_count INTEGER NOT NULL,
                        baseline_avg REAL NOT NULL,
                        ratio REAL NOT NULL,
                        message TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        acknowledged INTEGER NOT NULL DEFAULT 0,
                        UNIQUE(store_id, date, alert_type)
                    );
                    """
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

    def get_snapshot(self, store_id: str, kind: str) -> Optional[Any]:
        """Read a persisted store snapshot payload by kind."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT payload FROM store_snapshots
                    WHERE store_id = ? AND kind = ?
                    """,
                    (store_id, kind),
                ).fetchone()
                if not row:
                    return None
                return json.loads(row["payload"])
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

    def _check_connectivity(self) -> None:
        """Lightweight connectivity probe — raises on failure."""
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("SELECT 1")
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

    # ── K-002: waste_timeseries + alerts ──────────────────────────

    def upsert_waste_timeseries(
        self, store_id: str, date: str, total_count: int,
        event_count: int, top_skus: list,
    ) -> None:
        """UPSERT waste_timeseries 行。"""
        from datetime import datetime, timezone
        generated_at = datetime.now(timezone.utc).isoformat()
        top_skus_json = json.dumps(top_skus, ensure_ascii=False)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO waste_timeseries
                        (store_id, date, total_count, event_count, top_skus, generated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(store_id, date) DO UPDATE SET
                        total_count = excluded.total_count,
                        event_count = excluded.event_count,
                        top_skus = excluded.top_skus,
                        generated_at = excluded.generated_at
                    """,
                    (store_id, date, total_count, event_count, top_skus_json, generated_at),
                )
                conn.commit()
            finally:
                conn.close()

    def query_waste_trend(
        self, store_id: str, days: int = 30, include_compare: bool = True,
    ) -> dict:
        """查询趋势，返回 daily/trend/dates/comparison。缺失日期用0填充。"""
        from datetime import date as date_type, datetime, timedelta, timezone

        cutoff_dt = date_type.today() - timedelta(days=days - 1)
        cutoff = cutoff_dt.isoformat()

        daily_map: Dict[str, Dict[str, Any]] = {}
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT date, total_count, event_count, top_skus
                    FROM waste_timeseries
                    WHERE store_id = ? AND date >= ?
                    ORDER BY date ASC
                    """,
                    (store_id, cutoff),
                ).fetchall()
            finally:
                conn.close()

        for row in rows:
            try:
                top_skus = json.loads(row["top_skus"]) if row["top_skus"] else []
            except (json.JSONDecodeError, TypeError):
                top_skus = []
            daily_map[row["date"]] = {
                "date": row["date"],
                "total_count": row["total_count"],
                "event_count": row["event_count"],
                "top_skus": top_skus,
            }

        # 填充缺失日期
        today = date_type.today()
        cursor = cutoff_dt
        full_daily: list = []
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
                    "top_skus": [],
                })
            cursor += timedelta(days=1)

        trend = [d["total_count"] for d in full_daily]
        dates = [d["date"] for d in full_daily]

        result: Dict[str, Any] = {
            "store_id": store_id,
            "days": days,
            "daily": full_daily,
            "trend": trend,
            "dates": dates,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        if include_compare:
            result["comparison"] = compute_trend_comparison(full_daily)

        return result

    def check_and_create_waste_alert(
        self, store_id: str, date: str,
    ) -> dict:
        """检查今日是否需要告警，如果需要则创建（幂等）。"""
        from datetime import datetime, timezone

        # 获取今日 count
        today_count = 0
        seven_day_avg = 0.0
        with self._lock:
            conn = self._connect()
            try:
                # 今日数据
                row = conn.execute(
                    "SELECT total_count FROM waste_timeseries WHERE store_id = ? AND date = ?",
                    (store_id, date),
                ).fetchone()
                if row:
                    today_count = row["total_count"]

                # 7日均值（不含今日，前7天非零日均值）
                rows_7d = conn.execute(
                    """
                    SELECT total_count FROM waste_timeseries
                    WHERE store_id = ? AND date < ? AND total_count > 0
                    ORDER BY date DESC LIMIT 7
                    """,
                    (store_id, date),
                ).fetchall()
                vals_7d = [r["total_count"] for r in rows_7d]
                seven_day_avg = sum(vals_7d) / len(vals_7d) if vals_7d else 0.0
            finally:
                conn.close()

        triggered, ratio = check_alert(today_count, seven_day_avg)
        alert_id = None

        if triggered:
            message = format_alert_message(date, today_count, seven_day_avg, ratio)
            created_at = datetime.now(timezone.utc).isoformat()
            with self._lock:
                conn = self._connect()
                try:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO waste_alerts
                            (store_id, date, alert_type, current_count,
                             baseline_avg, ratio, message, created_at)
                        VALUES (?, ?, 'spike', ?, ?, ?, ?, ?)
                        """,
                        (store_id, date, today_count, round(seven_day_avg, 1), ratio, message, created_at),
                    )
                    conn.commit()
                    # 获取刚插入或已存在的 alert_id
                    row = conn.execute(
                        "SELECT id FROM waste_alerts WHERE store_id = ? AND date = ? AND alert_type = 'spike'",
                        (store_id, date),
                    ).fetchone()
                    if row:
                        alert_id = row["id"]
                finally:
                    conn.close()

        return {
            "store_id": store_id,
            "date": date,
            "alert_triggered": triggered,
            "current_count": today_count,
            "seven_day_avg": round(seven_day_avg, 1),
            "ratio": ratio,
            "threshold": 1.5,
            "alert_id": alert_id,
        }

    def list_waste_alerts(self, store_id: str, days: int = 7) -> list:
        """列出最近 N 天的告警。"""
        from datetime import date as date_type, timedelta

        cutoff = (date_type.today() - timedelta(days=days - 1)).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT id, store_id, date, alert_type, current_count,
                           baseline_avg, ratio, message, created_at, acknowledged
                    FROM waste_alerts
                    WHERE store_id = ? AND date >= ?
                    ORDER BY date DESC, id DESC
                    """,
                    (store_id, cutoff),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def ack_waste_alert(self, alert_id: int) -> bool:
        """确认告警。返回是否成功。"""
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "UPDATE waste_alerts SET acknowledged = 1 WHERE id = ?",
                    (alert_id,),
                )
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()
