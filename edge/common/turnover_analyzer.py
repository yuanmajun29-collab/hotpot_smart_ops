"""Table turnover analytics for front-hall scene events.

This module is intentionally framework-free so it can run from the Edge Agent,
batch jobs, or local Jetson scripts.  It consumes table state events from the
front_hall scene analyzer and produces per-table sessions, hourly/daily store
turnover aggregates, and low-turnover anomaly events.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional


TURNOVER_EVENT_TYPE = "table_turnover_stats"
LOW_TURNOVER_EVENT_TYPE = "table_turnover_low_anomaly"


def utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp without microseconds."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_ts(value: Optional[Any]) -> datetime:
    """Parse common timestamp values into timezone-aware UTC datetimes."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
    elif isinstance(value, str) and value.strip():
        raw = value.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
    else:
        dt = datetime.now(timezone.utc)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _date_key(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).date().isoformat()


def _hour_key(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat()


def normalize_table_state(state: Any) -> str:
    """Normalize front_hall/Hub table-state aliases to a compact state model."""
    raw = str(state or "").strip().lower()
    aliases = {
        "occupied": "dining",
        "customer_dining": "dining",
        "need_clean": "needs_cleaning",
        "need_cleaning": "needs_cleaning",
        "dirty": "needs_cleaning",
        "cleaning": "needs_cleaning",
        "completed": "empty",
        "ready": "empty",
        "available": "empty",
    }
    return aliases.get(raw, raw)


@dataclass
class TableSession:
    """A completed or in-progress table dining session."""

    session_id: str
    store_id: str
    table_id: str
    started_at: str
    dining_end_at: str = ""
    ended_at: str = ""
    dining_duration_min: float = 0.0
    cleaning_duration_min: float = 0.0
    completed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TableRuntime:
    """In-memory state for one table."""

    state: str = "unknown"
    changed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    current_session: Optional[TableSession] = None
    cleaning_started_at: Optional[datetime] = None


class HubEventPoster:
    """Small async Hub client that can also use Edge Agent's offline buffer."""

    def __init__(
        self,
        hub_url: str = "",
        api_key: str = "",
        endpoint: str = "/v1/events",
        inference_buffer: Any = None,
    ) -> None:
        self.hub_url = hub_url.rstrip("/")
        self.api_key = api_key
        self.endpoint = endpoint
        self.inference_buffer = inference_buffer

    async def post_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Post one event to Hub.  Returns a status dict and never raises."""
        store_id = event.get("store_id", "")
        endpoint = self.endpoint
        if store_id and "store_id=" not in endpoint:
            sep = "&" if "?" in endpoint else "?"
            endpoint = f"{endpoint}{sep}store_id={store_id}"

        if self.inference_buffer is not None:
            try:
                event_id = await self.inference_buffer.enqueue(endpoint, event, store_id=store_id)
                return {"ok": True, "buffered": True, "event_id": event_id}
            except Exception as exc:
                return {"ok": False, "buffered": False, "error": str(exc)}

        if not self.hub_url:
            return {"ok": False, "skipped": True, "error": "hub_url is empty"}

        try:
            import httpx

            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["X-Api-Key"] = self.api_key
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(f"{self.hub_url}{endpoint}", json=event, headers=headers)
                resp.raise_for_status()
                try:
                    return {"ok": True, "response": resp.json()}
                except ValueError:
                    return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


class TurnoverAnalyzer:
    """Analyze table turnover from front_hall table-state transitions.

    A turnover cycle is counted when a table that had a dining session moves
    through a cleaning/empty completion boundary.  The expected happy path is:
    dining -> needs_cleaning -> empty -> dining.
    """

    def __init__(
        self,
        store_id: str = "",
        total_tables: int = 0,
        hub_poster: Optional[HubEventPoster] = None,
    ) -> None:
        self.store_id = store_id
        self.total_tables = total_tables
        self.hub_poster = hub_poster
        self._tables: Dict[str, TableRuntime] = {}
        self._sessions: List[TableSession] = []
        self._daily_rates: Dict[str, Dict[str, float]] = {}
        self._last_events: List[Dict[str, Any]] = []

    @property
    def sessions(self) -> List[Dict[str, Any]]:
        """Return completed and in-progress sessions."""
        active = [
            rt.current_session.to_dict()
            for rt in self._tables.values()
            if rt.current_session is not None
        ]
        return [s.to_dict() for s in self._sessions] + active

    @property
    def table_count(self) -> int:
        """Configured table count, falling back to observed distinct tables."""
        return self.total_tables or max(len(self._tables), 1)

    def process_event(
        self,
        event: Dict[str, Any],
        store_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process one front_hall scene event and update table state."""
        sid = store_id or event.get("store_id") or self.store_id
        table_id = str(event.get("table_id") or event.get("table") or "").strip()
        if not table_id:
            raise ValueError("table_id is required")

        state = normalize_table_state(event.get("state") or event.get("status") or event.get("table_state"))
        if state not in {"empty", "dining", "needs_cleaning", "checkout", "unknown"}:
            state = "unknown"
        ts = _parse_ts(event.get("timestamp") or event.get("updated_at") or event.get("changed_at"))

        runtime = self._tables.setdefault(table_id, TableRuntime())
        prev_state = runtime.state
        prev_changed_at = runtime.changed_at
        completed_session: Optional[TableSession] = None

        if state == "dining" and prev_state != "dining":
            runtime.current_session = TableSession(
                session_id=uuid.uuid4().hex[:12],
                store_id=sid,
                table_id=table_id,
                started_at=ts.isoformat(),
            )
            runtime.cleaning_started_at = None

        elif state == "needs_cleaning" and runtime.current_session is not None:
            if not runtime.current_session.dining_end_at:
                runtime.current_session.dining_end_at = ts.isoformat()
                runtime.current_session.dining_duration_min = _minutes_between(
                    _parse_ts(runtime.current_session.started_at),
                    ts,
                )
            runtime.cleaning_started_at = ts

        elif state == "empty" and runtime.current_session is not None:
            session = runtime.current_session
            if not session.dining_end_at:
                session.dining_end_at = ts.isoformat()
                session.dining_duration_min = _minutes_between(_parse_ts(session.started_at), ts)
            if runtime.cleaning_started_at is not None:
                session.cleaning_duration_min = _minutes_between(runtime.cleaning_started_at, ts)
            session.ended_at = ts.isoformat()
            session.completed = True
            self._sessions.append(session)
            runtime.current_session = None
            runtime.cleaning_started_at = None
            completed_session = session

        runtime.state = state
        runtime.changed_at = ts

        record = {
            "store_id": sid,
            "table_id": table_id,
            "from_state": prev_state,
            "to_state": state,
            "changed_at": ts.isoformat(),
            "previous_changed_at": prev_changed_at.isoformat(),
            "completed_session": completed_session.to_dict() if completed_session else None,
        }
        self._last_events.append(record)
        self._last_events = self._last_events[-100:]
        return record

    def process_events(
        self,
        events: Iterable[Dict[str, Any]],
        store_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Process a batch of table-state events in timestamp order."""
        sorted_events = sorted(events, key=lambda e: _parse_ts(e.get("timestamp") or e.get("updated_at") or e.get("changed_at")))
        return [self.process_event(event, store_id=store_id) for event in sorted_events]

    def aggregate(
        self,
        store_id: Optional[str] = None,
        now: Optional[Any] = None,
        historical_daily_rates: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """Build hourly and daily turnover stats for one store."""
        sid = store_id or self.store_id
        current = _parse_ts(now)
        today = _date_key(current)
        total_tables = self.table_count
        completed = [s for s in self._sessions if not sid or s.store_id == sid]

        hourly_count: Dict[str, int] = {}
        daily_count: Dict[str, int] = {}
        dining_mins: List[float] = []
        cleaning_mins: List[float] = []
        per_table: Dict[str, Dict[str, Any]] = {}

        for session in completed:
            end_dt = _parse_ts(session.ended_at)
            hourly_count[_hour_key(end_dt)] = hourly_count.get(_hour_key(end_dt), 0) + 1
            daily_count[_date_key(end_dt)] = daily_count.get(_date_key(end_dt), 0) + 1
            dining_mins.append(session.dining_duration_min)
            cleaning_mins.append(session.cleaning_duration_min)
            bucket = per_table.setdefault(
                session.table_id,
                {"table_id": session.table_id, "completed_sessions": 0, "avg_dining_duration_min": 0.0},
            )
            bucket["completed_sessions"] += 1
            bucket["_dining_total"] = bucket.get("_dining_total", 0.0) + session.dining_duration_min

        hourly = [
            {
                "hour": hour,
                "completed_sessions": count,
                "turnover_rate": _rate(count, total_tables),
            }
            for hour, count in sorted(hourly_count.items())
        ]
        daily = [
            {
                "date": day,
                "completed_sessions": count,
                "turnover_rate": _rate(count, total_tables),
            }
            for day, count in sorted(daily_count.items())
        ]

        today_count = daily_count.get(today, 0)
        current_rate = _rate(today_count, total_tables)
        self._daily_rates.setdefault(sid, {})[today] = current_rate
        history = dict(self._daily_rates.get(sid, {}))
        if historical_daily_rates:
            history.update({k: float(v) for k, v in historical_daily_rates.items()})
        anomaly = self.detect_low_turnover_anomaly(sid, current_rate, today, history)

        for item in per_table.values():
            completed_count = max(item["completed_sessions"], 1)
            item["avg_dining_duration_min"] = round(item.pop("_dining_total", 0.0) / completed_count, 1)

        return {
            "store_id": sid,
            "generated_at": current.isoformat(),
            "total_tables": total_tables,
            "daily_turnover_rate": current_rate,
            "completed_sessions_today": today_count,
            "avg_dining_duration_min": _avg(dining_mins),
            "avg_cleaning_duration_min": _avg(cleaning_mins),
            "hourly": hourly,
            "daily": daily,
            "per_table": sorted(per_table.values(), key=lambda x: x["table_id"]),
            "anomaly": anomaly,
        }

    def detect_low_turnover_anomaly(
        self,
        store_id: str,
        current_rate: float,
        current_date: str,
        daily_rates: Optional[Dict[str, float]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Detect a >30% drop versus the previous 7 available daily rates."""
        history = daily_rates or self._daily_rates.get(store_id, {})
        try:
            base = date.fromisoformat(current_date)
        except ValueError:
            base = datetime.now(timezone.utc).date()
        values = []
        for offset in range(1, 8):
            key = (base - timedelta(days=offset)).isoformat()
            if key in history:
                values.append(float(history[key]))
        if not values:
            return None
        avg7 = sum(values) / len(values)
        if avg7 <= 0:
            return None
        drop_pct = round((avg7 - current_rate) / avg7 * 100, 1)
        if drop_pct <= 30.0:
            return None
        return {
            "type": LOW_TURNOVER_EVENT_TYPE,
            "store_id": store_id,
            "date": current_date,
            "current_rate": round(current_rate, 3),
            "avg_7d_rate": round(avg7, 3),
            "drop_pct": drop_pct,
            "severity": "warn" if drop_pct < 50 else "critical",
        }

    def build_stats_event(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        """Build a Hub event payload for turnover stats."""
        return {
            "event_type": TURNOVER_EVENT_TYPE,
            "source": "vision",
            "level": "info",
            "store_id": stats.get("store_id", self.store_id),
            "zone": "front_hall",
            "timestamp": stats.get("generated_at", utc_now_iso()),
            "message": (
                f"翻台率 {stats.get('daily_turnover_rate', 0):.2f}，"
                f"今日完成 {stats.get('completed_sessions_today', 0)} 桌次"
            ),
            "metadata": stats,
        }

    def build_anomaly_event(self, anomaly: Dict[str, Any]) -> Dict[str, Any]:
        """Build a Hub event payload for low-turnover anomaly."""
        return {
            "event_type": LOW_TURNOVER_EVENT_TYPE,
            "source": "vision",
            "level": anomaly.get("severity", "warn"),
            "store_id": anomaly.get("store_id", self.store_id),
            "zone": "front_hall",
            "timestamp": utc_now_iso(),
            "message": (
                f"翻台率较7日均值下降 {anomaly.get('drop_pct', 0):.1f}% "
                f"({anomaly.get('current_rate')} vs {anomaly.get('avg_7d_rate')})"
            ),
            "metadata": anomaly,
        }

    async def post_stats(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        """Post stats and optional anomaly to Hub as events."""
        if self.hub_poster is None:
            return {"ok": False, "skipped": True, "error": "hub_poster is not configured"}

        results = [await self.hub_poster.post_event(self.build_stats_event(stats))]
        if stats.get("anomaly"):
            results.append(await self.hub_poster.post_event(self.build_anomaly_event(stats["anomaly"])))
        return {"ok": all(r.get("ok") for r in results), "results": results}


def _minutes_between(start: datetime, end: datetime) -> float:
    return round(max((end - start).total_seconds(), 0.0) / 60.0, 1)


def _rate(completed_sessions: int, total_tables: int) -> float:
    return round(completed_sessions / max(total_tables, 1), 3)


def _avg(values: List[float]) -> float:
    clean = [float(v) for v in values if v is not None]
    return round(sum(clean) / len(clean), 1) if clean else 0.0


def analyzer_from_env(inference_buffer: Any = None) -> TurnoverAnalyzer:
    """Create a default analyzer using Edge Agent environment variables."""
    poster = HubEventPoster(
        hub_url=os.environ.get("HOTPOT_HUB_URL", ""),
        api_key=os.environ.get("HOTPOT_API_KEY", ""),
        inference_buffer=inference_buffer,
    )
    return TurnoverAnalyzer(
        store_id=os.environ.get("HOTPOT_STORE_ID", ""),
        total_tables=int(os.environ.get("HOTPOT_TOTAL_TABLES", "0") or 0),
        hub_poster=poster,
    )


def to_json(data: Dict[str, Any]) -> str:
    """Serialize analytics output for CLI/debug use."""
    return json.dumps(data, ensure_ascii=False, indent=2)
