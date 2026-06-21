"""22:00 daily report scheduler (DEV-423 / BL-06) — threading, no extra deps."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional
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


# ---- 三时段损耗调度 schedule profiles (LOSS-507) ----------------------------

class ScheduleProfile(NamedTuple):
    """A named time slot. ``weekday`` (Mon=0) None means every day. ``kind``
    selects the dispatch handler (e.g. restock / daily / weekly)."""
    name: str
    hour: int
    minute: int
    weekday: Optional[int] = None
    kind: str = "daily"


def due_profiles(profiles: List[ScheduleProfile], now: datetime) -> List[ScheduleProfile]:
    """Profiles whose slot matches ``now`` (hour, minute, and weekday if set)."""
    return [
        p for p in profiles
        if p.hour == now.hour and p.minute == now.minute
        and (p.weekday is None or p.weekday == now.weekday())
    ]


def default_loss_profiles() -> List[ScheduleProfile]:
    """三时段损耗调度：15:00 备货建议 / 22:00 损耗复盘 / 周一 09:00 损耗趋势周报。"""
    return [
        ScheduleProfile("restock", 15, 0, None, "restock"),
        ScheduleProfile("daily_loss", 22, 0, None, "daily"),
        ScheduleProfile("weekly", 9, 0, 0, "weekly"),
    ]


def validate_profiles(profiles: List[ScheduleProfile]) -> None:
    """Fail fast on invalid schedule configuration."""
    seen = set()
    for p in profiles:
        if not p.name:
            raise ValueError("schedule profile name is required")
        if p.name in seen:
            raise ValueError(f"duplicate schedule profile name: {p.name}")
        seen.add(p.name)
        if not 0 <= p.hour <= 23:
            raise ValueError(f"schedule profile {p.name} hour must be 0..23")
        if not 0 <= p.minute <= 59:
            raise ValueError(f"schedule profile {p.name} minute must be 0..59")
        if p.weekday is not None and not 0 <= p.weekday <= 6:
            raise ValueError(f"schedule profile {p.name} weekday must be 0..6 or None")


class DailyReportScheduler:
    """Background loop: once per local day per store at configured time."""

    def __init__(
        self,
        generate_fn: Optional[Callable[[str, bool], Dict[str, Any]]] = None,
        *,
        stores: Optional[List[str]] = None,
        hour: int = DEFAULT_HOUR,
        minute: int = DEFAULT_MINUTE,
        tz_name: str = DEFAULT_TZ,
        check_interval_sec: float = 60.0,
        profiles: Optional[List[ScheduleProfile]] = None,
        dispatch: Optional[Dict[str, Callable[[str], Any]]] = None,
    ) -> None:
        self.generate_fn = generate_fn
        self.stores = list(stores or PILOT_STORES)
        self.hour = hour
        self.minute = minute
        self.tz_name = tz_name
        self.check_interval_sec = check_interval_sec
        # Legacy single-slot mode: synthesize one daily profile from generate_fn.
        if profiles is None:
            profiles = [ScheduleProfile("daily_report", hour, minute, None, "daily")]
            if dispatch is None and generate_fn is not None:
                dispatch = {"daily": lambda sid: generate_fn(sid, True)}
        validate_profiles(profiles)
        self.profiles = profiles
        self.dispatch = dispatch or {}
        # dedup key: f"{profile.name}:{store_id}" -> local date already run
        self._last_run_date: Dict[str, str] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="daily-report-scheduler", daemon=True)
        self._thread.start()
        slots = ", ".join(f"{p.name}@{p.hour:02d}:{p.minute:02d}" for p in self.profiles)
        print(
            f"[daily_scheduler] started stores={self.stores} profiles=[{slots}] {self.tz_name}",
            flush=True,
        )

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _run_due(self, now: datetime) -> None:
        """Fire every due profile once per (profile, store) per local day."""
        date = now.strftime("%Y-%m-%d")
        for profile in due_profiles(self.profiles, now):
            handler = self.dispatch.get(profile.kind)
            if handler is None:
                print(f"[daily_scheduler] WARN: no handler for profile {profile.name}", flush=True)
                continue
            for sid in self.stores:
                key = f"{profile.name}:{sid}"
                if self._last_run_date.get(key) == date:
                    continue
                try:
                    handler(sid)
                    self._last_run_date[key] = date
                except Exception as exc:
                    print(f"[daily_scheduler] ERROR {profile.name}/{sid}: {exc}", flush=True)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._run_due(datetime.now(ZoneInfo(self.tz_name)))
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
