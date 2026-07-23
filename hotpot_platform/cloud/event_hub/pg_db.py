"""PostgreSQL persistence for Event Hub (DEV-101 P0).

Connection-pooled, drop-in replacement for db.HubDatabase.
Activate via: export HOTPOT_DATABASE_URL=postgresql://user:pass@host/db
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone, date as date_type
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

from hotpot_platform.cloud.event_hub.daily_report_store import PG_DAILY_REPORTS_SCHEMA
from hotpot_platform.cloud.event_hub.iot_readings_store import PG_IOT_READINGS_SCHEMA
from hotpot_platform.cloud.event_hub.receiving_store import PG_RECEIVING_SCHEMA
from hotpot_platform.cloud.event_hub.sop_assign_store import PG_SOP_ASSIGN_SCHEMA
from hotpot_platform.cloud.event_hub.task_store import PG_TASKS_SCHEMA
from hotpot_platform.cloud.event_hub.domain.waste_timeseries import (
    check_alert,
    compute_trend_comparison,
    format_alert_message,
)

MAX_EVENTS_PER_STORE = 500
POOL_MIN_CONN = 2
POOL_MAX_CONN = 10


class PostgresHubDatabase:
    """PostgreSQL backend with same interface as HubDatabase.

    Uses psycopg2 ThreadedConnectionPool instead of a global threading.Lock,
    so multiple tenants can read/write concurrently without lock contention.
    """

    def __init__(self, database_url: str) -> None:
        try:
            import psycopg2
            import psycopg2.extras
            from psycopg2 import pool as pg_pool
        except ImportError as exc:
            raise RuntimeError(
                "psycopg2-binary required for PostgreSQL: pip install psycopg2-binary"
            ) from exc

        self.database_url = database_url
        self._psycopg2 = psycopg2
        self._psycopg2_extras = psycopg2.extras

        # ── connection pool ──
        self._pool = pg_pool.ThreadedConnectionPool(
            minconn=POOL_MIN_CONN,
            maxconn=POOL_MAX_CONN,
            dsn=database_url,
        )

        self._init_schema()

    @property
    def db_path(self):
        """Sidecar sqlite path compatibility — for log messages."""
        parsed = urlparse(self.database_url)
        dbname = (parsed.path or "/hotpot").lstrip("/")
        return f"pg://{parsed.hostname}/{dbname}"

    # ── thread-local pool helpers ───────────────────────────────

    def _getconn(self):
        """Borrow a connection from the pool."""
        return self._pool.getconn()

    def _putconn(self, conn, *, close: bool = False):
        """Return (or close) a connection to the pool."""
        if close:
            self._pool.putconn(conn, close=True)
        else:
            self._pool.putconn(conn)

    # ── schema ──────────────────────────────────────────────────

    def _init_schema(self) -> None:
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS events (
                        event_id TEXT PRIMARY KEY,
                        store_id TEXT NOT NULL,
                        level TEXT,
                        source TEXT,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_events_store
                        ON events(store_id, created_at DESC);

                    CREATE TABLE IF NOT EXISTS store_snapshots (
                        store_id TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        PRIMARY KEY (store_id, kind)
                    );

                    CREATE TABLE IF NOT EXISTS device_registry (
                        device_id TEXT PRIMARY KEY,
                        payload JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    );
                    """
                    + PG_RECEIVING_SCHEMA
                    + PG_SOP_ASSIGN_SCHEMA
                    + PG_TASKS_SCHEMA
                    + PG_IOT_READINGS_SCHEMA
                    + PG_DAILY_REPORTS_SCHEMA
                    + """
                    CREATE TABLE IF NOT EXISTS waste_timeseries (
                        id SERIAL PRIMARY KEY,
                        store_id TEXT NOT NULL,
                        date TEXT NOT NULL,
                        total_count INTEGER NOT NULL DEFAULT 0,
                        event_count INTEGER NOT NULL DEFAULT 0,
                        top_skus TEXT NOT NULL DEFAULT '[]',
                        generated_at TIMESTAMPTZ NOT NULL,
                        UNIQUE(store_id, date)
                    );
                    CREATE INDEX IF NOT EXISTS idx_wts_store_date
                        ON waste_timeseries(store_id, date DESC);

                    CREATE TABLE IF NOT EXISTS waste_alerts (
                        id SERIAL PRIMARY KEY,
                        store_id TEXT NOT NULL,
                        date TEXT NOT NULL,
                        alert_type TEXT NOT NULL DEFAULT 'spike',
                        current_count INTEGER NOT NULL,
                        baseline_avg REAL NOT NULL,
                        ratio REAL NOT NULL,
                        message TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        acknowledged INTEGER NOT NULL DEFAULT 0,
                        UNIQUE(store_id, date, alert_type)
                    );
                    """
                )
            conn.commit()
        finally:
            self._putconn(conn)

    # ── event persistence ───────────────────────────────────────

    def persist_event(self, store_id: str, event: Dict[str, Any]) -> None:
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO events(event_id, store_id, level, source, payload, created_at)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (event_id) DO UPDATE SET
                        payload = EXCLUDED.payload,
                        level = EXCLUDED.level,
                        source = EXCLUDED.source
                    """,
                    (
                        event["event_id"],
                        store_id,
                        event.get("level"),
                        event.get("source"),
                        json.dumps(event, ensure_ascii=False),
                        event.get("timestamp") or datetime.now(timezone.utc).isoformat(),
                    ),
                )
                cur.execute(
                    """
                    DELETE FROM events WHERE event_id IN (
                        SELECT event_id FROM events WHERE store_id = %s
                        ORDER BY created_at DESC OFFSET %s
                    )
                    """,
                    (store_id, MAX_EVENTS_PER_STORE),
                )
            conn.commit()
        finally:
            self._putconn(conn)

    def persist_snapshot(self, store_id: str, kind: str, payload: Any) -> None:
        updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO store_snapshots(store_id, kind, payload, updated_at)
                    VALUES (%s, %s, %s::jsonb, %s)
                    ON CONFLICT (store_id, kind) DO UPDATE SET
                        payload = EXCLUDED.payload,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (store_id, kind, json.dumps(payload, ensure_ascii=False), updated_at),
                )
            conn.commit()
        finally:
            self._putconn(conn)

    def get_snapshot(self, store_id: str, kind: str) -> Optional[Any]:
        """Read a persisted store snapshot payload by kind."""
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload FROM store_snapshots
                    WHERE store_id = %s AND kind = %s
                    """,
                    (store_id, kind),
                )
                row = cur.fetchone()
                if not row:
                    return None
                payload = row[0]
                return payload if isinstance(payload, dict) else json.loads(payload)
        finally:
            self._putconn(conn)

    def update_devices(self, devices: Dict[str, Any]) -> None:
        updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM device_registry")
                for device_id, payload in devices.items():
                    cur.execute(
                        """
                        INSERT INTO device_registry(device_id, payload, updated_at)
                        VALUES (%s, %s::jsonb, %s)
                        ON CONFLICT (device_id) DO UPDATE SET
                            payload = EXCLUDED.payload,
                            updated_at = EXCLUDED.updated_at
                        """,
                        (device_id, json.dumps(payload, ensure_ascii=False), updated_at),
                    )
            conn.commit()
        finally:
            self._putconn(conn)

    def get_devices(self) -> Dict[str, Any]:
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT device_id, payload FROM device_registry")
                return {
                    device_id: payload if isinstance(payload, dict) else json.loads(payload)
                    for device_id, payload in cur.fetchall()
                }
        finally:
            self._putconn(conn)

    def load_store_into(self, hub: Any, store_id: str) -> None:
        store = hub.get_store(store_id)
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload FROM events WHERE store_id = %s
                    ORDER BY created_at DESC LIMIT %s
                    """,
                    (store_id, MAX_EVENTS_PER_STORE),
                )
                rows = cur.fetchall()
                events = [row[0] if isinstance(row[0], dict) else json.loads(row[0]) for row in rows]
                store.load_events_batch(events)

                cur.execute(
                    "SELECT kind, payload FROM store_snapshots WHERE store_id = %s",
                    (store_id,),
                )
                for kind, payload in cur.fetchall():
                    data = payload if isinstance(payload, dict) else json.loads(payload)
                    store.load_snapshot(kind, data)
        finally:
            self._putconn(conn)

    def _check_connectivity(self) -> None:
        """Lightweight connectivity probe — raises on failure."""
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        finally:
            self._putconn(conn)

    def is_empty(self) -> bool:
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM events")
                return cur.fetchone()[0] == 0
        finally:
            self._putconn(conn)

    def hydrate_hub(self, hub: Any, store_ids: Optional[List[str]] = None) -> None:
        ids = store_ids or [s["store_id"] for s in hub.list_stores()]
        for sid in ids:
            self.load_store_into(hub, sid)

    def on_persist(self, store_id: str, kind: str, payload: Any) -> None:
        if kind == "event":
            self.persist_event(store_id, payload)
        else:
            self.persist_snapshot(store_id, kind, payload)

    # ── waste count stats (from events, real-time) ──────────────

    def query_waste_count_stats(
        self, store_id: str, days: int = 7
    ) -> Dict[str, Any]:
        """Query last N days of vlm_waste_estimate events, aggregated by day."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).strftime("%Y-%m-%d")

        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload, created_at FROM events
                    WHERE store_id = %s
                      AND payload->>'event_type' = 'vlm_waste_estimate'
                      AND created_at >= %s
                    ORDER BY created_at DESC
                    """,
                    (store_id, cutoff),
                )
                rows = cur.fetchall()
        finally:
            self._putconn(conn)

        # ── aggregate by day ──
        daily_map: Dict[str, Dict[str, Any]] = {}
        for payload_val, created_at in rows:
            try:
                if isinstance(payload_val, dict):
                    payload = payload_val
                else:
                    payload = json.loads(payload_val)
            except (json.JSONDecodeError, TypeError):
                continue

            meta = payload.get("metadata", {})
            items = meta.get("items", [])
            total_count = meta.get("total_waste_count", 0)

            if not total_count:
                for item in items:
                    c = item.get("count", 0)
                    if isinstance(c, (int, float)):
                        total_count += int(c)

            # PG returns datetime objects for TIMESTAMPTZ
            if isinstance(created_at, datetime):
                date_key = created_at.strftime("%Y-%m-%d")
            else:
                date_key = str(created_at)[:10] if created_at else "unknown"

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

            for item in items:
                sku = item.get("sku", "unknown")
                count = item.get("count", 0)
                if isinstance(count, (int, float)) and count > 0:
                    entry["items"].append({
                        "sku": sku,
                        "count": int(count),
                        "waste_type": item.get("waste_type", "备餐废弃"),
                    })

        # ── sort + fill gaps ──
        daily = sorted(daily_map.values(), key=lambda d: d["date"])

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

    # ── waste timeseries (K-002) ────────────────────────────────

    def upsert_waste_timeseries(
        self, store_id: str, date: str, total_count: int,
        event_count: int, top_skus: list,
    ) -> None:
        """UPSERT waste_timeseries row."""
        generated_at = datetime.now(timezone.utc).isoformat()
        top_skus_json = json.dumps(top_skus, ensure_ascii=False)
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO waste_timeseries
                        (store_id, date, total_count, event_count, top_skus, generated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT(store_id, date) DO UPDATE SET
                        total_count = EXCLUDED.total_count,
                        event_count = EXCLUDED.event_count,
                        top_skus = EXCLUDED.top_skus,
                        generated_at = EXCLUDED.generated_at
                    """,
                    (store_id, date, total_count, event_count, top_skus_json, generated_at),
                )
            conn.commit()
        finally:
            self._putconn(conn)

    def query_waste_trend(
        self, store_id: str, days: int = 30, include_compare: bool = True,
    ) -> dict:
        """Query waste_timeseries trend; fill missing dates with 0."""
        cutoff_dt = date_type.today() - timedelta(days=days - 1)
        cutoff = cutoff_dt.isoformat()

        daily_map: Dict[str, Dict[str, Any]] = {}
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT date, total_count, event_count, top_skus
                    FROM waste_timeseries
                    WHERE store_id = %s AND date >= %s
                    ORDER BY date ASC
                    """,
                    (store_id, cutoff),
                )
                rows = cur.fetchall()
        finally:
            self._putconn(conn)

        for date_val, total_count, event_count, top_skus_val in rows:
            try:
                top_skus = json.loads(top_skus_val) if top_skus_val else []
            except (json.JSONDecodeError, TypeError):
                top_skus = []
            date_str = str(date_val)[:10] if date_val else ""
            daily_map[date_str] = {
                "date": date_str,
                "total_count": total_count,
                "event_count": event_count,
                "top_skus": top_skus,
            }

        # fill missing dates
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
        """Check if today's waste count triggers a spike alert (idempotent)."""
        today_count = 0
        seven_day_avg = 0.0

        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                # today
                cur.execute(
                    "SELECT total_count FROM waste_timeseries WHERE store_id = %s AND date = %s",
                    (store_id, date),
                )
                row = cur.fetchone()
                if row:
                    today_count = row[0]

                # 7-day average (prior 7 non-zero days)
                cur.execute(
                    """
                    SELECT total_count FROM waste_timeseries
                    WHERE store_id = %s AND date < %s AND total_count > 0
                    ORDER BY date DESC LIMIT 7
                    """,
                    (store_id, date),
                )
                vals_7d = [r[0] for r in cur.fetchall()]
                seven_day_avg = sum(vals_7d) / len(vals_7d) if vals_7d else 0.0
        finally:
            self._putconn(conn)

        triggered, ratio = check_alert(today_count, seven_day_avg)
        alert_id = None

        if triggered:
            message = format_alert_message(date, today_count, seven_day_avg, ratio)
            created_at = datetime.now(timezone.utc).isoformat()
            conn = self._getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO waste_alerts
                            (store_id, date, alert_type, current_count,
                             baseline_avg, ratio, message, created_at)
                        VALUES (%s, %s, 'spike', %s, %s, %s, %s, %s)
                        ON CONFLICT (store_id, date, alert_type) DO NOTHING
                        """,
                        (store_id, date, today_count, round(seven_day_avg, 1),
                         ratio, message, created_at),
                    )
                conn.commit()

                # Get id of inserted/existing alert
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM waste_alerts WHERE store_id = %s AND date = %s AND alert_type = 'spike'",
                        (store_id, date),
                    )
                    row = cur.fetchone()
                    if row:
                        alert_id = row[0]
            finally:
                self._putconn(conn)

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
        """List waste alerts for last N days."""
        cutoff = (date_type.today() - timedelta(days=days - 1)).isoformat()
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, store_id, date, alert_type, current_count,
                           baseline_avg, ratio, message, created_at, acknowledged
                    FROM waste_alerts
                    WHERE store_id = %s AND date >= %s
                    ORDER BY date DESC, id DESC
                    """,
                    (store_id, cutoff),
                )
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
        finally:
            self._putconn(conn)

    def ack_waste_alert(self, alert_id: int) -> bool:
        """Acknowledge a waste alert. Returns True if updated."""
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE waste_alerts SET acknowledged = 1 WHERE id = %s",
                    (alert_id,),
                )
                conn.commit()
                return cur.rowcount > 0
        finally:
            self._putconn(conn)

    # ── multi-tenant query helpers ──────────────────────────────

    def query_events_by_tenant(
        self,
        tenant_id: str,
        limit: int = 100,
        event_type: Optional[str] = None,
        level: Optional[str] = None,
        since: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Tenant-scoped event query (tenant_id = store_id)."""
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                conditions = ["store_id = %s"]
                params: List[Any] = [tenant_id]

                if event_type:
                    conditions.append("payload->>'event_type' = %s")
                    params.append(event_type)
                if level:
                    conditions.append("level = %s")
                    params.append(level)
                if since:
                    conditions.append("created_at >= %s")
                    params.append(since)

                where = " AND ".join(conditions)
                cur.execute(
                    f"""
                    SELECT payload FROM events
                    WHERE {where}
                    ORDER BY created_at DESC LIMIT %s
                    """,
                    params + [limit],
                )
                return [
                    row[0] if isinstance(row[0], dict) else json.loads(row[0])
                    for row in cur.fetchall()
                ]
        finally:
            self._putconn(conn)

    def query_tenant_stats(
        self, tenant_id: str, days: int = 7
    ) -> Dict[str, Any]:
        """Aggregated stats for a tenant (= store_id) across all event types."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT level, COUNT(*) as cnt
                    FROM events WHERE store_id = %s AND created_at >= %s
                    GROUP BY level
                    """,
                    (tenant_id, cutoff.isoformat()),
                )
                by_level = {row[0] or "none": row[1] for row in cur.fetchall()}

                cur.execute(
                    """
                    SELECT payload->>'event_type' as event_type, COUNT(*) as cnt
                    FROM events WHERE store_id = %s AND created_at >= %s
                    GROUP BY payload->>'event_type'
                    """,
                    (tenant_id, cutoff.isoformat()),
                )
                by_type = {row[0] or "none": row[1] for row in cur.fetchall()}

                return {
                    "tenant_id": tenant_id,
                    "days": days,
                    "by_level": by_level,
                    "by_type": by_type,
                    "total": sum(by_level.values()),
                }
        finally:
            self._putconn(conn)

    def list_tenants(self) -> List[Dict[str, Any]]:
        """List all tenants (store_ids) with event counts."""
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT store_id, COUNT(*) as event_count,
                           MAX(created_at) as last_seen
                    FROM events GROUP BY store_id
                    ORDER BY last_seen DESC
                    """
                )
                return [
                    {
                        "tenant_id": row[0],
                        "event_count": row[1],
                        "last_seen": row[2].isoformat() if row[2] else None,
                    }
                    for row in cur.fetchall()
                ]
        finally:
            self._putconn(conn)

    def multi_tenant_summary(self) -> Dict[str, Any]:
        """Cross-tenant summary for the unified dashboard."""
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                # Total tenants
                cur.execute("SELECT COUNT(DISTINCT store_id) FROM events")
                total_tenants = cur.fetchone()[0]

                # Recent alerts (last 24h)
                cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                cur.execute(
                    """
                    SELECT level, COUNT(*) as cnt
                    FROM events WHERE created_at >= %s
                    AND level IN ('critical','warning')
                    GROUP BY level
                    """,
                    (cutoff.isoformat(),),
                )
                alert_counts = {row[0]: row[1] for row in cur.fetchall()}

                # Total events today
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                cur.execute(
                    """
                    SELECT COUNT(*) FROM events
                    WHERE created_at::date = %s
                    """,
                    (today,),
                )
                today_events = cur.fetchone()[0]

                return {
                    "total_tenants": total_tenants,
                    "critical_alerts_24h": alert_counts.get("critical", 0),
                    "warning_alerts_24h": alert_counts.get("warning", 0),
                    "events_today": today_events,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
        finally:
            self._putconn(conn)
