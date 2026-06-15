"""Alert gateway — WeChat Work webhook mock + push log (DEV-306)."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROUTES_FILE = PROJECT_ROOT / "demo" / "data" / "alert_routes.json"
PUSH_LOG_FILE = PROJECT_ROOT / "demo" / "data" / "alert_push.log"

LEVEL_LABELS = {"critical": "严重", "warn": "警告", "info": "信息"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class AlertGateway:
    """Route critical/warn events to WeChat Work (mock file + optional webhook)."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._routes = self._load_routes()
        self._init_schema()

    def _load_routes(self) -> Dict[str, Any]:
        if ROUTES_FILE.exists():
            return json.loads(ROUTES_FILE.read_text(encoding="utf-8"))
        return {}

    def _init_schema(self) -> None:
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS alert_pushes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT NOT NULL,
                        store_id TEXT NOT NULL,
                        level TEXT NOT NULL,
                        channel TEXT NOT NULL,
                        title TEXT,
                        body TEXT NOT NULL,
                        status TEXT DEFAULT 'sent',
                        created_at TEXT NOT NULL,
                        UNIQUE(event_id, channel)
                    );
                    CREATE INDEX IF NOT EXISTS idx_alert_pushes_store ON alert_pushes(store_id, created_at DESC);

                    CREATE TABLE IF NOT EXISTS alert_acks (
                        event_id TEXT NOT NULL,
                        store_id TEXT NOT NULL,
                        ack_by TEXT NOT NULL,
                        ack_note TEXT DEFAULT '',
                        ack_at TEXT NOT NULL,
                        PRIMARY KEY (event_id, store_id)
                    );
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def _store_route(self, store_id: str) -> Dict[str, Any]:
        route = dict(self._routes.get(store_id, {}))
        defaults = self._routes.get("defaults", {})
        route.setdefault("store_name", store_id)
        route.setdefault("dashboard_url", "http://127.0.0.1:3000/alerts.html")
        route.setdefault("recipients", ["店长"])
        route.setdefault("push_warn", os.environ.get(defaults.get("push_warn_env", "HOTPOT_PUSH_WARN"), "") == "1")
        webhook = route.get("webhook_url") or os.environ.get(defaults.get("webhook_env", "HOTPOT_WECHAT_WEBHOOK"), "")
        route["webhook_url"] = webhook
        return route

    def format_wechat_card(self, event: Dict[str, Any], store_id: str) -> Dict[str, str]:
        route = self._store_route(store_id)
        level = event.get("level", "info")
        label = LEVEL_LABELS.get(level, level)
        title = self._event_title(event)
        ts = event.get("timestamp", utc_now_iso())
        local_time = ts.replace("T", " ").split("+")[0] if ts else ""
        body_lines = [
            f"【{label}】{title}",
            f"门店：{route.get('store_name', store_id)}",
            event.get("message", ""),
            f"时间：{local_time}",
            f"👉 打开看板：{route.get('dashboard_url')}?store_id={store_id}",
        ]
        return {
            "title": f"【{label}】{title}",
            "body": "\n".join(body_lines),
            "markdown": "\n".join(body_lines),
        }

    def _event_title(self, event: Dict[str, Any]) -> str:
        mapping = {
            "cold_chain_high": "冷链超温",
            "cold_chain_warn": "冷链异常",
            "kitchen_smoke": "后厨烟雾",
            "gas_leak": "燃气泄漏",
            "table_need_clean": "待清台超时",
            "iot_weight_short": "来料短重",
        }
        et = event.get("event_type", "告警")
        return mapping.get(et, et)

    def should_push(self, event: Dict[str, Any], store_id: str) -> bool:
        level = event.get("level", "info")
        if level == "critical":
            return True
        if level == "warn":
            return self._store_route(store_id).get("push_warn", False)
        return False

    def handle_event(self, event: Dict[str, Any], store_id: str) -> Optional[Dict[str, Any]]:
        if not self.should_push(event, store_id):
            return None
        if self.is_acked(event.get("event_id", ""), store_id):
            return None

        card = self.format_wechat_card(event, store_id)
        route = self._store_route(store_id)
        result = {
            "event_id": event.get("event_id"),
            "store_id": store_id,
            "level": event.get("level"),
            "channel": "wechat_work",
            "recipients": route.get("recipients", []),
            "card": card,
            "webhook_sent": False,
        }

        if self._record_push(event, store_id, card):
            self._append_file_log(card, store_id, event)
            if route.get("webhook_url"):
                result["webhook_sent"] = self._post_webhook(route["webhook_url"], card)
        return result

    def _record_push(self, event: Dict[str, Any], store_id: str, card: Dict[str, str]) -> bool:
        eid = event.get("event_id")
        if not eid:
            return False
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO alert_pushes
                    (event_id, store_id, level, channel, title, body, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        eid,
                        store_id,
                        event.get("level", "info"),
                        "wechat_work",
                        card["title"],
                        card["body"],
                        utc_now_iso(),
                    ),
                )
                conn.commit()
                return conn.total_changes > 0
            finally:
                conn.close()

    def _append_file_log(self, card: Dict[str, str], store_id: str, event: Dict[str, Any]) -> None:
        PUSH_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {
                "ts": utc_now_iso(),
                "store_id": store_id,
                "event_id": event.get("event_id"),
                "level": event.get("level"),
                "title": card["title"],
                "body": card["body"],
            },
            ensure_ascii=False,
        )
        with PUSH_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _post_webhook(self, url: str, card: Dict[str, str]) -> bool:
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": card["markdown"]},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=10)
            return True
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"[AlertGateway] webhook failed: {exc}", file=__import__("sys").stderr)
            return False

    def ack(self, event_id: str, store_id: str, ack_by: str, ack_note: str = "") -> Dict[str, Any]:
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO alert_acks(event_id, store_id, ack_by, ack_note, ack_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (event_id, store_id, ack_by, ack_note, utc_now_iso()),
                )
                conn.commit()
            finally:
                conn.close()
        return {"ok": True, "event_id": event_id, "store_id": store_id, "ack_by": ack_by}

    def is_acked(self, event_id: str, store_id: str) -> bool:
        if not event_id:
            return False
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                row = conn.execute(
                    "SELECT 1 FROM alert_acks WHERE event_id = ? AND store_id = ?",
                    (event_id, store_id),
                ).fetchone()
                return row is not None
            finally:
                conn.close()

    def list_pushes(self, store_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            try:
                if store_id:
                    rows = conn.execute(
                        """
                        SELECT * FROM alert_pushes WHERE store_id = ?
                        ORDER BY created_at DESC LIMIT ?
                        """,
                        (store_id, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM alert_pushes ORDER BY created_at DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def list_unacked_critical(self, store_id: str, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            e
            for e in events
            if e.get("level") == "critical" and not self.is_acked(e.get("event_id", ""), store_id)
        ]

    def list_acks(self, store_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            try:
                if store_id:
                    rows = conn.execute(
                        "SELECT * FROM alert_acks WHERE store_id = ? ORDER BY ack_at DESC",
                        (store_id,),
                    ).fetchall()
                else:
                    rows = conn.execute("SELECT * FROM alert_acks ORDER BY ack_at DESC").fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def count_escalations(self, store_id: str, events: List[Dict[str, Any]], minutes: int = 30) -> Dict[str, Any]:
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        pending = []
        for e in events:
            if e.get("level") != "critical":
                continue
            eid = e.get("event_id", "")
            if self.is_acked(eid, store_id):
                continue
            ts = e.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if dt <= cutoff:
                pending.append(e)
        return {"count": len(pending), "threshold_minutes": minutes, "events": pending}
