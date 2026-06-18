"""22:00 daily report scheduler (DEV-423 / BL-06) — threading, no extra deps."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TZ = os.environ.get("HOTPOT_STORE_TZ", "Asia/Shanghai")
DEFAULT_HOUR = int(os.environ.get("HOTPOT_DAILY_REPORT_HOUR", "22"))
DEFAULT_MINUTE = int(os.environ.get("HOTPOT_DAILY_REPORT_MINUTE", "0"))
PILOT_STORES = ("store_yuhuan", "store_jiaojiang")

STORE_NAMES = {
    "store_yuhuan": "冯校长火锅·玉环店",
    "store_jiaojiang": "冯校长火锅·椒江店",
}


def local_today(tz_name: str = DEFAULT_TZ) -> str:
    return datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d")


def should_run_now(
    *,
    hour: int = DEFAULT_HOUR,
    minute: int = DEFAULT_MINUTE,
    tz_name: str = DEFAULT_TZ,
) -> bool:
    now = datetime.now(ZoneInfo(tz_name))
    return now.hour == hour and now.minute == minute


class DailyReportScheduler:
    """Background loop: once per local day per store at configured time."""

    def __init__(
        self,
        generate_fn: Callable[[str, bool], Dict[str, Any]],
        *,
        stores: Optional[List[str]] = None,
        hour: int = DEFAULT_HOUR,
        minute: int = DEFAULT_MINUTE,
        tz_name: str = DEFAULT_TZ,
        check_interval_sec: float = 60.0,
    ) -> None:
        self.generate_fn = generate_fn
        self.stores = list(stores or PILOT_STORES)
        self.hour = hour
        self.minute = minute
        self.tz_name = tz_name
        self.check_interval_sec = check_interval_sec
        self._last_run_date: Dict[str, str] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="daily-report-scheduler", daemon=True)
        self._thread.start()
        print(
            f"[daily_scheduler] started stores={self.stores} "
            f"at {self.hour:02d}:{self.minute:02d} {self.tz_name}",
            flush=True,
        )

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _loop(self) -> None:
        while not self._stop.is_set():
            if should_run_now(hour=self.hour, minute=self.minute, tz_name=self.tz_name):
                today = local_today(self.tz_name)
                for sid in self.stores:
                    if self._last_run_date.get(sid) == today:
                        continue
                    try:
                        self.generate_fn(sid, True)
                        self._last_run_date[sid] = today
                    except Exception as exc:
                        print(f"[daily_scheduler] ERROR {sid}: {exc}", flush=True)
            self._stop.wait(self.check_interval_sec)


def generate_daily_report_for_store(
    hub: Any,
    db: Any,
    alert_gateway: Any,
    store_id: str,
    *,
    push: bool = False,
    report_date: Optional[str] = None,
) -> Dict[str, Any]:
    from cloud.event_hub.daily_report_store import daily_report_store
    from cloud.llm_report.report_agent import RuleBasedReportAgent

    tz_name = DEFAULT_TZ
    rdate = report_date or local_today(tz_name)
    existing = daily_report_store(db).get_by_date(store_id, rdate)
    if existing and not push:
        return {
            "ok": True,
            "store_id": store_id,
            "report_date": rdate,
            "report_id": existing["report_id"],
            "markdown": existing["markdown"],
            "cached": True,
            "pushed": bool(existing.get("pushed")),
        }

    summary = hub.get_store(store_id).get_summary()
    store_name = STORE_NAMES.get(store_id, store_id)
    agent = RuleBasedReportAgent()
    markdown = agent.generate(summary, store_name=store_name)

    row = daily_report_store(db).save(
        store_id,
        rdate,
        markdown,
        json.dumps(summary, ensure_ascii=False),
        pushed=False,
    )

    pushed = False
    if push:
        pushed = alert_gateway.push_daily_report(store_id, markdown, rdate, summary=summary)

    if pushed:
        daily_report_store(db).mark_pushed(store_id, rdate)

    return {
        "ok": True,
        "store_id": store_id,
        "report_date": rdate,
        "report_id": row["report_id"],
        "markdown": markdown,
        "cached": False,
        "pushed": pushed,
    }
