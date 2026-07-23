"""Daily SOP scorecard engine.

The scorer is framework-free and consumes violation records produced by
``edge.agent.modules.sop_infer`` or equivalent SOP event payloads.  It computes
a 0-100 daily compliance score per store, applies severity weights, tracks
day-over-day trend, and can post the scorecard to Hub as an event.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from edge.common.turnover_analyzer import HubEventPoster, utc_now_iso


SOP_SCORECARD_EVENT_TYPE = "sop_daily_scorecard"


SEVERITY_PENALTIES = {
    "critical": 25,
    "major": 10,
    "warning": 10,
    "warn": 10,
    "minor": 3,
    "info": 1,
}


def _parse_ts(value: Optional[Any]) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
    elif isinstance(value, str) and value.strip():
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _day_key(value: Optional[Any]) -> str:
    return _parse_ts(value).date().isoformat()


def _severity(value: Any) -> str:
    raw = str(value or "minor").strip().lower()
    return raw if raw in SEVERITY_PENALTIES else "minor"


@dataclass
class SopViolationRecord:
    """Normalized SOP violation used by the daily scorer."""

    violation_id: str
    store_id: str
    station_id: str
    violation_type: str
    severity: str
    timestamp: str
    message: str = ""
    source_event_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SopScorer:
    """Compute daily SOP compliance scorecards from violation events."""

    def __init__(
        self,
        store_id: str = "",
        hub_poster: Optional[HubEventPoster] = None,
        baseline_score: int = 100,
    ) -> None:
        self.store_id = store_id
        self.hub_poster = hub_poster
        self.baseline_score = baseline_score
        self._violations: Dict[str, List[SopViolationRecord]] = {}
        self._score_history: Dict[str, Dict[str, float]] = {}
        self._last_scorecards: Dict[str, Dict[str, Any]] = {}

    def record_violation(self, payload: Dict[str, Any], store_id: Optional[str] = None) -> SopViolationRecord:
        """Normalize and store one violation event."""
        sid = store_id or payload.get("store_id") or self.store_id
        ts = _parse_ts(payload.get("timestamp") or payload.get("updated_at"))
        record = SopViolationRecord(
            violation_id=str(payload.get("violation_id") or payload.get("event_id") or uuid.uuid4().hex[:12]),
            store_id=sid,
            station_id=str(payload.get("station_id") or payload.get("station") or "unknown"),
            violation_type=str(payload.get("type") or payload.get("violation_type") or payload.get("event_type") or "sop_violation"),
            severity=_severity(payload.get("severity") or payload.get("level")),
            timestamp=ts.isoformat(),
            message=str(payload.get("message") or ""),
            source_event_id=str(payload.get("event_id") or ""),
        )
        self._violations.setdefault(sid, []).append(record)
        return record

    def record_violations(
        self,
        payloads: Iterable[Dict[str, Any]],
        store_id: Optional[str] = None,
    ) -> List[SopViolationRecord]:
        """Normalize and store a batch of violation events."""
        return [self.record_violation(payload, store_id=store_id) for payload in payloads]

    def record_sop_infer_result(
        self,
        result: Dict[str, Any],
        store_id: Optional[str] = None,
    ) -> List[SopViolationRecord]:
        """Read violation events from ``sop_infer.py`` result shape."""
        sid = store_id or result.get("store_id") or self.store_id
        station_id = result.get("station_id", "unknown")
        timestamp = result.get("timestamp") or utc_now_iso()
        violations = result.get("violations") or []
        normalized = []
        for item in violations:
            if not isinstance(item, dict):
                continue
            payload = dict(item)
            payload.setdefault("store_id", sid)
            payload.setdefault("station_id", station_id)
            payload.setdefault("timestamp", timestamp)
            normalized.append(payload)
        return self.record_violations(normalized, store_id=sid)

    def daily_scorecard(
        self,
        store_id: Optional[str] = None,
        day: Optional[str] = None,
        total_checks: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Generate a daily 0-100 SOP compliance scorecard."""
        sid = store_id or self.store_id
        target_day = day or datetime.now(timezone.utc).date().isoformat()
        records = [
            record
            for record in self._violations.get(sid, [])
            if _day_key(record.timestamp) == target_day
        ]

        by_severity: Dict[str, int] = {"critical": 0, "major": 0, "minor": 0}
        by_station: Dict[str, int] = {}
        penalty = 0
        for record in records:
            severity = _severity(record.severity)
            canonical = "major" if severity in {"warning", "warn"} else severity
            if canonical not in by_severity:
                canonical = "minor"
            by_severity[canonical] += 1
            by_station[record.station_id] = by_station.get(record.station_id, 0) + 1
            penalty += SEVERITY_PENALTIES.get(severity, SEVERITY_PENALTIES["minor"])

        score = max(0, min(100, self.baseline_score - penalty))
        checks = total_checks if total_checks is not None else max(len(records), 1)
        compliance_rate = round(max(0.0, (checks - len(records)) / max(checks, 1)) * 100, 1)
        trend = self._trend(sid, target_day, score)

        scorecard = {
            "store_id": sid,
            "date": target_day,
            "generated_at": utc_now_iso(),
            "score": score,
            "compliance_rate": compliance_rate,
            "violation_count": len(records),
            "penalty": penalty,
            "severity_counts": by_severity,
            "station_counts": by_station,
            "trend": trend,
            "violations": [record.to_dict() for record in records],
        }
        self._score_history.setdefault(sid, {})[target_day] = float(score)
        self._last_scorecards[sid] = scorecard
        return scorecard

    def _trend(self, store_id: str, day: str, score: float) -> Dict[str, Any]:
        history = self._score_history.get(store_id, {})
        previous_days = sorted(k for k in history if k < day)
        previous_score = history[previous_days[-1]] if previous_days else None
        if previous_score is None:
            status = "stable"
            delta = 0.0
        else:
            delta = round(score - previous_score, 1)
            if delta >= 3:
                status = "improving"
            elif delta <= -3:
                status = "worsening"
            else:
                status = "stable"
        return {"status": status, "delta": delta, "previous_score": previous_score}

    def build_scorecard_event(self, scorecard: Dict[str, Any]) -> Dict[str, Any]:
        """Build Hub event payload for a daily SOP scorecard."""
        level = "critical" if scorecard.get("score", 100) < 70 else "warn" if scorecard.get("score", 100) < 85 else "info"
        return {
            "event_type": SOP_SCORECARD_EVENT_TYPE,
            "source": "vision",
            "level": level,
            "store_id": scorecard.get("store_id", self.store_id),
            "zone": "kitchen",
            "timestamp": scorecard.get("generated_at", utc_now_iso()),
            "message": (
                f"SOP日评分 {scorecard.get('score', 0)}，"
                f"违规 {scorecard.get('violation_count', 0)} 项，趋势 {scorecard.get('trend', {}).get('status', 'stable')}"
            ),
            "metadata": scorecard,
        }

    async def post_scorecard(self, scorecard: Dict[str, Any]) -> Dict[str, Any]:
        """Post a daily scorecard to Hub as an event."""
        if self.hub_poster is None:
            return {"ok": False, "skipped": True, "error": "hub_poster is not configured"}
        return await self.hub_poster.post_event(self.build_scorecard_event(scorecard))


def scorer_from_env(inference_buffer: Any = None) -> SopScorer:
    """Create a default scorer using Edge Agent environment variables."""
    poster = HubEventPoster(
        hub_url=os.environ.get("HOTPOT_HUB_URL", ""),
        api_key=os.environ.get("HOTPOT_API_KEY", ""),
        inference_buffer=inference_buffer,
    )
    return SopScorer(store_id=os.environ.get("HOTPOT_STORE_ID", ""), hub_poster=poster)
