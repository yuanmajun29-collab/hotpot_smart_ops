"""Edge → Hub client with offline queue (DEV-105)."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional


class EdgeHubClient:
    """POST to Event Hub with retry and SQLite offline queue."""

    def __init__(
        self,
        hub_url: str,
        store_id: str,
        api_key: str = "",
        queue_db: Optional[Path] = None,
    ) -> None:
        self.hub_url = hub_url.rstrip("/")
        self.store_id = store_id
        self.api_key = api_key or os.environ.get("HOTPOT_API_KEY", "")
        self.queue_db = queue_db or Path(f"demo/data/stores/{store_id}/edge_queue.db")
        self.queue_db.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_queue()

    def _init_queue(self) -> None:
        with self._lock:
            conn = sqlite3.connect(str(self.queue_db))
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS pending (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        path TEXT NOT NULL,
                        query TEXT,
                        body TEXT NOT NULL,
                        created_at TEXT DEFAULT (datetime('now'))
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json", "X-Store-Id": self.store_id}
        if self.api_key:
            h["X-Api-Key"] = self.api_key
        return h

    def _enqueue(self, path: str, body: Any, query: str = "") -> None:
        with self._lock:
            conn = sqlite3.connect(str(self.queue_db))
            try:
                conn.execute(
                    "INSERT INTO pending(path, query, body) VALUES (?, ?, ?)",
                    (path, query, json.dumps(body, ensure_ascii=False)),
                )
                conn.commit()
            finally:
                conn.close()

    def post(self, path: str, body: Any, *, store_query: bool = True) -> bool:
        query = f"store_id={urllib.parse.quote(self.store_id)}" if store_query else ""
        url = self.hub_url + path
        if query:
            url += ("&" if "?" in url else "?") + query
        req = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=8)
            return True
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"[EdgeHubClient] queue offline: {path} ({exc})", file=__import__("sys").stderr)
            self._enqueue(path, body, query)
            return False

    def post_event(self, event: Dict[str, Any]) -> bool:
        return self.post("/events", event, store_query=False)

    def try_post(
        self,
        path: str,
        body: Any,
        *,
        store_query: bool = True,
    ) -> bool:
        """Best-effort POST without writing to the built-in SQLite queue.

        Used by components that own a stronger domain-specific store-and-forward
        buffer and need a pure success/failure signal.
        """
        query = f"store_id={urllib.parse.quote(self.store_id)}" if store_query else ""
        url = self.hub_url + path
        if query:
            url += ("&" if "?" in url else "?") + query
        req = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=8)
            return True
        except (urllib.error.URLError, TimeoutError):
            return False

    def try_post_event(self, event: Dict[str, Any]) -> bool:
        return self.try_post("/events", event, store_query=False)

    def post_events(self, events: list) -> int:
        ok = 0
        for ev in events:
            if self.post_event(ev):
                ok += 1
        return ok

    def post_tables(self, tables: list) -> bool:
        return self.post("/tables", tables)

    def flush_queue(self) -> int:
        sent = 0
        with self._lock:
            conn = sqlite3.connect(str(self.queue_db))
            try:
                rows = conn.execute("SELECT id, path, query, body FROM pending ORDER BY id").fetchall()
                for row_id, path, query, body in rows:
                    url = self.hub_url + path
                    if query:
                        url += ("&" if "?" in url else "?") + query
                    req = urllib.request.Request(
                        url,
                        data=body.encode("utf-8"),
                        headers=self._headers(),
                        method="POST",
                    )
                    try:
                        urllib.request.urlopen(req, timeout=8)
                        conn.execute("DELETE FROM pending WHERE id = ?", (row_id,))
                        sent += 1
                    except (urllib.error.URLError, TimeoutError):
                        break
                conn.commit()
            finally:
                conn.close()
        if sent:
            print(f"[EdgeHubClient] flushed {sent} queued item(s)")
        return sent

    def pending_count(self) -> int:
        with self._lock:
            conn = sqlite3.connect(str(self.queue_db))
            try:
                return conn.execute("SELECT COUNT(*) FROM pending").fetchone()[0]
            finally:
                conn.close()
