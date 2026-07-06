"""SQLite persistence for Event Hub (DEV-101, PG-compatible schema later)."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from platform.cloud.event_hub.daily_report_store import SQLITE_DAILY_REPORTS_SCHEMA
from platform.cloud.event_hub.iot_readings_store import SQLITE_IOT_READINGS_SCHEMA
from platform.cloud.event_hub.receiving_store import SQLITE_RECEIVING_SCHEMA
from platform.cloud.event_hub.sop_assign_store import SQLITE_SOP_ASSIGN_SCHEMA
from platform.cloud.event_hub.task_store import SQLITE_TASKS_SCHEMA

MAX_EVENTS_PER_STORE = 500


def create_hub_database(
    db_path: Path,
    database_url: Optional[str] = None,
) -> Union["HubDatabase", Any]:
    """Factory: PostgreSQL when HOTPOT_DATABASE_URL set, else SQLite."""
    url = database_url or os.environ.get("HOTPOT_DATABASE_URL", "")
    if url:
        from platform.cloud.event_hub.pg_db import PostgresHubDatabase

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
