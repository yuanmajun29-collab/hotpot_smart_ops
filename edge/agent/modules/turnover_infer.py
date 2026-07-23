"""Turnover analytics router for Edge Agent.

Provides:
  - POST /infer/turnover: ingest front_hall table-state events and aggregate stats
  - GET /status/turnover: module status and latest in-memory aggregate
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from edge.agent.config import API_KEY, HUB_URL, STORE_ID
from edge.common.turnover_analyzer import (
    HubEventPoster,
    TurnoverAnalyzer,
)


router = APIRouter(tags=["turnover"])

# 由 server.py 在配置驱动下设置
_active = False
_analyzer: Optional[TurnoverAnalyzer] = None
_last_stats: Optional[Dict[str, Any]] = None
buffer = None


class TurnoverTableEvent(BaseModel):
    """One table-state event from front_hall scene analysis."""

    table_id: str
    state: Optional[str] = None
    status: Optional[str] = None
    table_state: Optional[str] = None
    timestamp: Optional[str] = None
    updated_at: Optional[str] = None
    changed_at: Optional[str] = None
    confidence: Optional[float] = None


class TurnoverInferRequest(BaseModel):
    """Turnover analysis request."""

    events: List[TurnoverTableEvent] = Field(default_factory=list)
    store_id: Optional[str] = None
    total_tables: Optional[int] = None
    historical_daily_rates: Optional[Dict[str, float]] = None
    push_hub: bool = True


def _check_active() -> None:
    if not _active:
        raise HTTPException(503, "turnover 模块未激活（配置中无 turnover zone）")


def _model_to_dict(model: Any) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=True)
    return model.dict(exclude_none=True)


def _get_analyzer(total_tables: Optional[int] = None) -> TurnoverAnalyzer:
    """Build or reuse the process-local turnover analyzer."""
    global _analyzer
    if _analyzer is None:
        _analyzer = TurnoverAnalyzer(
            store_id=STORE_ID,
            total_tables=total_tables or 0,
            hub_poster=HubEventPoster(hub_url=HUB_URL, api_key=API_KEY, inference_buffer=buffer),
        )
    if total_tables is not None:
        _analyzer.total_tables = total_tables
    if _analyzer.hub_poster is not None:
        _analyzer.hub_poster.inference_buffer = buffer
    return _analyzer


@router.post("/infer/turnover")
async def turnover_infer(req: TurnoverInferRequest) -> Dict[str, Any]:
    """Ingest table-state events, compute turnover stats, and optionally post Hub events."""
    global _last_stats
    _check_active()
    if not req.events:
        raise HTTPException(400, "请提供至少一条桌态事件")

    started = time.perf_counter()
    analyzer = _get_analyzer(req.total_tables)
    event_payloads = [_model_to_dict(item) for item in req.events]

    try:
        transitions = analyzer.process_events(event_payloads, store_id=req.store_id or STORE_ID)
        stats = analyzer.aggregate(
            store_id=req.store_id or STORE_ID,
            historical_daily_rates=req.historical_daily_rates,
        )
        hub_result = await analyzer.post_stats(stats) if req.push_hub else {"skipped": True}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"翻台率分析失败: {exc}") from exc

    _last_stats = stats
    return {
        "ok": True,
        "store_id": stats["store_id"],
        "processed_events": len(event_payloads),
        "transitions": transitions,
        "stats": stats,
        "hub": hub_result,
        "total_ms": round((time.perf_counter() - started) * 1000, 1),
    }


@router.get("/status/turnover")
def turnover_status() -> Dict[str, Any]:
    """Return turnover module status and latest aggregate snapshot."""
    analyzer = _get_analyzer()
    return {
        "module": "turnover",
        "active": _active,
        "hub": HUB_URL,
        "store_id": STORE_ID,
        "total_tables": analyzer.total_tables,
        "session_count": len(analyzer.sessions),
        "last_stats": _last_stats,
    }
