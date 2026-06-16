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
UAT_ROOT = PROJECT_ROOT / "deploy" / "uat"


def _store_webhook_env_key(store_id: str) -> str:
    return f"HOTPOT_WECHAT_WEBHOOK_{store_id.upper().replace('-', '_')}"


def _mask_webhook_url(url: str) -> str:
    if not url:
        return ""
    if len(url) <= 24:
        return url[:8] + "…"
    return url[:20] + "…" + url[-6:]


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

    def _uat_alert_overlay(self, store_id: str) -> Dict[str, Any]:
        path = UAT_ROOT / store_id / "alert.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def resolve_webhook_url(self, store_id: str, route: Optional[Dict[str, Any]] = None) -> str:
        """DEV-414: store file → per-store env → global env."""
        route = route or {}
        if route.get("webhook_url"):
            return str(route["webhook_url"])

        overlay = self._uat_alert_overlay(store_id)
        if overlay.get("webhook_url"):
            return str(overlay["webhook_url"])

        store_env = overlay.get("webhook_env") or _store_webhook_env_key(store_id)
        url = os.environ.get(store_env, "")
        if url:
            return url

        defaults = self._routes.get("defaults", {})
        global_env = defaults.get("webhook_env", "HOTPOT_WECHAT_WEBHOOK")
        return os.environ.get(global_env, "")

    def route_status(self, store_id: str) -> Dict[str, Any]:
        route = self._store_route(store_id)
        webhook = route.get("webhook_url", "")
        overlay = self._uat_alert_overlay(store_id)
        return {
            "store_id": store_id,
            "store_name": route.get("store_name", store_id),
            "webhook_configured": bool(webhook),
            "webhook_url_masked": _mask_webhook_url(webhook),
            "webhook_source": (
                "route_file"
                if self._routes.get(store_id, {}).get("webhook_url")
                else "uat_alert"
                if overlay.get("webhook_url")
                else "env_store"
                if os.environ.get(overlay.get("webhook_env") or _store_webhook_env_key(store_id), "")
                else "env_global"
                if os.environ.get(self._routes.get("defaults", {}).get("webhook_env", "HOTPOT_WECHAT_WEBHOOK"), "")
                else "none"
            ),
            "push_warn": bool(route.get("push_warn")),
            "recipients": route.get("recipients", []),
            "dashboard_url": route.get("dashboard_url"),
        }

    def _store_route(self, store_id: str) -> Dict[str, Any]:
        route = dict(self._routes.get(store_id, {}))
        overlay = self._uat_alert_overlay(store_id)
        route.update({k: v for k, v in overlay.items() if k not in ("webhook_env",)})
        defaults = self._routes.get("defaults", {})
        route.setdefault("store_name", overlay.get("store_name") or store_id)
        route.setdefault("dashboard_url", overlay.get("dashboard_url", "http://127.0.0.1:3000/alerts.html"))
        route.setdefault("recipients", overlay.get("recipients", ["店长"]))
        push_warn_env = overlay.get("push_warn_env") or defaults.get("push_warn_env", "HOTPOT_PUSH_WARN")
        route.setdefault(
            "push_warn",
            overlay.get("push_warn", os.environ.get(push_warn_env, "") == "1"),
        )
        route["webhook_url"] = self.resolve_webhook_url(store_id, route)
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

    def send_test_push(self, store_id: str) -> Dict[str, Any]:
        """Send a synthetic critical card to verify webhook (DEV-414 checklist)."""
        event = {
            "event_id": f"test-push-{int(datetime.now(timezone.utc).timestamp())}",
            "event_type": "kitchen_smoke",
            "level": "critical",
            "message": "【测试】企微 webhook 联调探针 — 请忽略",
            "timestamp": utc_now_iso(),
            "source": "system",
        }
        card = self.format_wechat_card(event, store_id)
        route = self._store_route(store_id)
        webhook_sent = False
        error = ""
        if route.get("webhook_url"):
            webhook_sent = self._post_webhook(route["webhook_url"], card)
            if not webhook_sent:
                error = "webhook POST failed or errcode != 0"
        else:
            error = "webhook not configured"
        self._append_file_log(card, store_id, event)
        return {
            "ok": webhook_sent,
            "store_id": store_id,
            "event_id": event["event_id"],
            "webhook_sent": webhook_sent,
            "webhook_configured": bool(route.get("webhook_url")),
            "card": card,
            "error": error or None,
        }

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
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode()
                if not raw:
                    return True
                data = json.loads(raw)
                return int(data.get("errcode", 0)) == 0
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
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

    def format_daily_report_card(
        self,
        store_id: str,
        report_date: str,
        summary: Optional[Dict[str, Any]] = None,
        *,
        acked_critical: int = 0,
    ) -> Dict[str, str]:
        """WeChat daily report card per push_notification_templates.md §5 (DEV-424)."""
        route = self._store_route(store_id)
        store_name = route.get("store_name", store_id)
        dash = route.get("dashboard_url", "http://127.0.0.1:3000/alerts.html")
        base = dash.replace("/alerts.html", "").rstrip("/")
        report_url = f"{base}/report.html?store_id={store_id}&date={report_date}"

        summary = summary or {}
        tables = summary.get("table_state_counts", {})
        levels = summary.get("by_level", {})
        pos = summary.get("pos_stats", {})
        sop = summary.get("sop_stats", {})
        cost = summary.get("cost_stats", {})

        need_clean = tables.get("need_clean", 0)
        turnover_rate = pos.get("turnover_rate", "—")
        sop_rate = sop.get("compliance_rate", "—")
        cost_var = cost.get("variance_rate_pct", cost.get("variance_pct", "—"))
        critical = levels.get("critical", 0)

        body_lines = [
            f"【运营日报】{store_name} · {report_date}",
            f"{report_date} 运营摘要",
            f"· 翻台：待清 {need_clean} 桌 · 翻台率 {turnover_rate}",
            f"· SOP：合规 {sop_rate}%",
            f"· 来料：偏差 {cost_var}%",
            f"· 安全：严重告警 {critical} 条（已处理 {acked_critical}）",
            f"👉 查看完整日报",
            report_url,
        ]
        markdown = (
            f"**【运营日报】{store_name} · {report_date}**\n"
            f"> {report_date} 运营摘要\n"
            f"> · 翻台：待清 **{need_clean}** 桌 · 翻台率 **{turnover_rate}**\n"
            f"> · SOP：合规 **{sop_rate}%**\n"
            f"> · 来料：偏差 **{cost_var}%**\n"
            f"> · 安全：严重告警 **{critical}** 条（已处理 **{acked_critical}**）\n"
            f"> [点击查看完整日报]({report_url})"
        )
        return {
            "title": f"【运营日报】{store_name} · {report_date}",
            "body": "\n".join(body_lines),
            "markdown": markdown,
            "report_url": report_url,
        }

    def push_daily_report(
        self,
        store_id: str,
        markdown: str,
        report_date: str,
        summary: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Push daily report card to WeChat Work (DEV-424)."""
        route = self._store_route(store_id)
        acked = len(
            [
                a
                for a in self.list_acks(store_id)
                if a.get("ack_at", "").startswith(report_date)
            ]
        )
        card = self.format_daily_report_card(
            store_id, report_date, summary, acked_critical=acked
        )
        event = {
            "event_id": f"daily-report-{store_id}-{report_date}",
            "event_type": "daily_report",
            "level": "info",
            "message": card["title"],
            "timestamp": utc_now_iso(),
        }
        self._record_push(event, store_id, card)
        self._append_file_log(card, store_id, event)
        if route.get("webhook_url"):
            return self._post_webhook(route["webhook_url"], card)
        return False

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
