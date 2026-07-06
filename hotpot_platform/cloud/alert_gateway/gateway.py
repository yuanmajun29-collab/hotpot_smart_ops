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

    # ---- 任务督办企微推送（DEV-526 / ADR-010）------------------------------

    _TASK_KIND = {
        "dispatch":       {"tag": "任务", "lead": "新任务派办，请尽快认领"},
        "accept_overdue": {"tag": "督办", "lead": "派办后超时未认领，已升级"},
        "done_overdue":   {"tag": "超时", "lead": "任务已逾期未闭环，已升级"},
    }
    _PRIO_LEVEL = {"P0": "critical", "P1": "warn", "P2": "info"}

    def format_task_card(self, task: Dict[str, Any], store_id: str, kind: str,
                         *, sla: str = "", overdue_minutes: Optional[int] = None) -> Dict[str, str]:
        meta = self._TASK_KIND.get(kind, self._TASK_KIND["dispatch"])
        route = self._store_route(store_id)
        title = task.get("title") or task.get("task_id") or "任务"
        prio = task.get("priority", "P1")
        assignee = task.get("assignee_id") or task.get("assignee_group") or "待派办"
        dash = str(route.get("dashboard_url") or "").replace("alerts.html", "tasks.html") or \
            "http://127.0.0.1:3000/tasks.html"
        lines = [
            f"【{meta['tag']}·{prio}】{title}",
            f"门店：{route.get('store_name', store_id)}",
            f"责任人：{assignee}",
            meta["lead"],
        ]
        if kind == "accept_overdue" and sla:
            lines.append(f"认领时限：{sla}")
        if kind == "done_overdue" and overdue_minutes is not None:
            lines.append(f"已逾期：{overdue_minutes} 分钟")
        lines.append(f"👉 打开任务中心：{dash}?store_id={store_id}")
        body = "\n".join(lines)
        return {"title": f"【{meta['tag']}·{prio}】{title}", "body": body, "markdown": body}

    def push_task_card(self, task: Dict[str, Any], store_id: str, kind: str,
                       *, sla: str = "", overdue_minutes: Optional[int] = None,
                       dedup_token: Optional[str] = None) -> Dict[str, Any]:
        """Push a task督办 card.

        Idempotent per (task_id, kind, dedup_token) via a synthetic event_id.
        ``dispatch`` leaves ``dedup_token`` None so a task is announced once. For
        recurring escalations the scheduler passes a per-round token (e.g. an
        hour bucket or escalation seq) so each round re-pushes with refreshed
        overdue_minutes instead of being silently deduped forever.
        """
        card = self.format_task_card(task, store_id, kind, sla=sla, overdue_minutes=overdue_minutes)
        level = self._PRIO_LEVEL.get(task.get("priority", "P1"), "warn")
        # escalations are at least warn so they always surface
        if kind in ("accept_overdue", "done_overdue") and level == "info":
            level = "warn"
        route = self._store_route(store_id)
        event_id = f"task:{task.get('task_id')}:{kind}"
        if dedup_token:
            event_id += f":{dedup_token}"
        pseudo = {
            "event_id": event_id,
            "level": level,
            "event_type": f"task_{kind}",
            "message": card["body"],
            "timestamp": utc_now_iso(),
        }
        result = {
            "task_id": task.get("task_id"),
            "kind": kind,
            "store_id": store_id,
            "level": level,
            "channel": "wechat_work",
            "recipients": route.get("recipients", []),
            "card": card,
            "pushed": False,
            "webhook_sent": False,
        }
        if self._record_push(pseudo, store_id, card):
            self._append_file_log(card, store_id, pseudo)
            result["pushed"] = True
            if route.get("webhook_url"):
                result["webhook_sent"] = self._post_webhook(route["webhook_url"], card)
        return result

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
            "👉 查看完整日报",
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

    # ---- 损耗备货建议推送（15:00 restock，LOSS-507 runtime）------------------

    def format_loss_restock_card(
        self, store_id: str, report_date: str, budget: Dict[str, Any]
    ) -> Dict[str, str]:
        """Restock advice card from a loss-budget result (compute_loss_budget)."""
        route = self._store_route(store_id)
        store_name = route.get("store_name", store_id)
        dash = route.get("dashboard_url", "http://127.0.0.1:3000/alerts.html")
        base = dash.replace("/alerts.html", "").rstrip("/")
        cost_url = f"{base}/cost.html?store_id={store_id}&date={report_date}"
        source = budget.get("source", "rule")
        items = budget.get("items") or []
        title = f"【今日备货建议】{store_name} · {report_date}"
        lines = [title, "今晚损耗预算 TopN："]
        for it in items[:5]:
            qty = it.get("forecast_qty")
            qty_txt = f"建议{qty}{it.get('forecast_unit') or ''}" if qty is not None else "建议待定"
            lines.append(
                f"· {it.get('sku') or it.get('ref_id')}：{qty_txt}，"
                f"预算损耗 ¥{it.get('budget_loss_amount', 0)}（{it.get('suggested_action') or it.get('reason') or ''}）"
            )
        if not items:
            lines.append("· 暂无显著损耗风险")
        lines.append(f"来源：{source}")
        lines.append(f"👉 打开损耗页：{cost_url}")
        body = "\n".join(lines)
        return {"title": title, "body": body, "markdown": body, "cost_url": cost_url}

    def push_loss_restock_advice(
        self, store_id: str, report_date: str, budget: Dict[str, Any], *,
        dedup_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Push the 15:00 restock advice card. Idempotent per (store, date)."""
        card = self.format_loss_restock_card(store_id, report_date, budget)
        route = self._store_route(store_id)
        event_id = f"loss-restock-{store_id}-{report_date}"
        if dedup_token:
            event_id += f":{dedup_token}"
        event = {
            "event_id": event_id,
            "event_type": "loss_restock_advice",
            "level": "info",
            "message": card["title"],
            "timestamp": utc_now_iso(),
        }
        result = {
            "store_id": store_id,
            "date": report_date,
            "channel": "wechat_work",
            "event_id": event_id,
            "card": card,
            "pushed": False,
            "webhook_sent": False,
        }
        if self._record_push(event, store_id, card):
            self._append_file_log(card, store_id, event)
            result["pushed"] = True
            if route.get("webhook_url"):
                result["webhook_sent"] = self._post_webhook(route["webhook_url"], card)
        return result

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
