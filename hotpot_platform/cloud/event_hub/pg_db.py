"""PostgreSQL persistence for Event Hub (DEV-101 P0)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from hotpot_platform.cloud.event_hub.daily_report_store import PG_DAILY_REPORTS_SCHEMA
from hotpot_platform.cloud.event_hub.iot_readings_store import PG_IOT_READINGS_SCHEMA
from hotpot_platform.cloud.event_hub.receiving_store import PG_RECEIVING_SCHEMA
from hotpot_platform.cloud.event_hub.sop_assign_store import PG_SOP_ASSIGN_SCHEMA

MAX_EVENTS_PER_STORE = 500


class PostgresHubDatabase:
    """PostgreSQL backend with same interface as HubDatabase."""

    def __init__(self, database_url: str) -> None:
        try:
            import psycopg2
            import psycopg2.extras
        except ImportError as exc:
            raise RuntimeError("psycopg2-binary required for PostgreSQL: pip install psycopg2-binary") from exc

        self.database_url = database_url
        self._lock = threading.Lock()
        self._psycopg2 = psycopg2
        self._init_schema()

    @property
    def db_path(self):
        """Alert gateway compatibility — sidecar sqlite path when using PG."""
        parsed = urlparse(self.database_url)
        dbname = (parsed.path or "/hotpot").lstrip("/")
        return f"pg://{parsed.hostname}/{dbname}"

    def _connect(self):
        return self._psycopg2.connect(self.database_url)

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._connect()
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
                        CREATE INDEX IF NOT EXISTS idx_events_store ON events(store_id, created_at DESC);

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
                        + PG_IOT_READINGS_SCHEMA
                        + PG_DAILY_REPORTS_SCHEMA
                    )
                conn.commit()
            finally:
                conn.close()

    def persist_event(self, store_id: str, event: Dict[str, Any]) -> None:
        with self._lock:
            conn = self._connect()
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
                conn.close()

    def persist_snapshot(self, store_id: str, kind: str, payload: Any) -> None:
        updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with self._lock:
            conn = self._connect()
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
                conn.close()

    def update_devices(self, devices: Dict[str, Any]) -> None:
        updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with self._lock:
            conn = self._connect()
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
                conn.close()

    def get_devices(self) -> Dict[str, Any]:
        with self._lock:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT device_id, payload FROM device_registry")
                    return {
                        device_id: payload if isinstance(payload, dict) else json.loads(payload)
                        for device_id, payload in cur.fetchall()
                    }
            finally:
                conn.close()

    def load_store_into(self, hub: Any, store_id: str) -> None:
        store = hub.get_store(store_id)
        with self._lock:
            conn = self._connect()
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
                conn.close()

    def is_empty(self) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM events")
                    return cur.fetchone()[0] == 0
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
