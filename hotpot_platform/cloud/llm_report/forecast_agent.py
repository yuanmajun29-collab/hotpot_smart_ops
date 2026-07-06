"""Loss-budget 备货预测 agent (LOSS-505+ LLM 接线).

Produces per-SKU 备货建议量 (forecast_qty) with a reason from the loss-budget
TopN. Two backends mirror report_agent.py:
  - RuleForecastAgent: no LLM → returns {} (loss-budget stays source="rule").
  - LLMForecastAgent: OpenAI-compatible chat; graceful → {} on any failure so the
    endpoint always degrades to the rule baseline (frozen contract §2.1).

The chat call is injectable (``chat_fn``) so tests never hit a real API.
"""

from __future__ import annotations

import json
import math
import os
from typing import Any, Callable, Dict, List, Optional


class RuleForecastAgent:
    """No-LLM baseline: no 备货量 forecast."""

    def forecast(self, items: List[Dict[str, Any]], *, store_id: str,
                 date: Optional[str] = None, **_ctx: Any) -> Dict[str, Dict[str, Any]]:
        return {}


def _build_prompt(items: List[Dict[str, Any]], store_id: str, date: Optional[str]) -> str:
    lines = [
        f"门店 {store_id} {date or ''} 今晚损耗预算 TopN。请基于历史消耗与风险，给每个 ref_id 的"
        "建议备货量（份）与简短理由。只输出 JSON：{ref_id: {forecast_qty, forecast_unit, reason}}。",
    ]
    for it in items:
        lines.append(
            f"- ref_id={it.get('ref_id')} sku={it.get('sku')} "
            f"预算损耗¥{it.get('budget_loss_amount')} 原因={it.get('reason')}"
        )
    return "\n".join(lines)


def _extract_json(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    if raw.lower().startswith("json"):
        raw = raw[4:].strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start:end + 1]
    return raw


def _clean_entry(value: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    raw_qty = value.get("forecast_qty")
    try:
        qty = float(raw_qty)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(qty) or qty < 0:
        return None
    unit = value.get("forecast_unit")
    if not isinstance(unit, str) or not unit.strip():
        unit = "份"
    reason = value.get("reason")
    if not isinstance(reason, str):
        reason = ""
    return {
        "forecast_qty": int(qty) if qty.is_integer() else round(qty, 2),
        "forecast_unit": unit.strip()[:16],
        "reason": reason.strip()[:160],
    }


class LLMForecastAgent:
    def __init__(self, api_key: str = "", base_url: str = "https://api.openai.com/v1",
                 model: str = "gpt-4o-mini", *, chat_fn: Optional[Callable[[str], str]] = None) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._chat_fn = chat_fn  # injectable for tests

    def _chat(self, prompt: str) -> str:
        if self._chat_fn is not None:
            return self._chat_fn(prompt)
        import urllib.request
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

    def forecast(self, items: List[Dict[str, Any]], *, store_id: str,
                 date: Optional[str] = None, **_ctx: Any) -> Dict[str, Dict[str, Any]]:
        if not items:
            return {}
        try:
            parsed = json.loads(_extract_json(self._chat(_build_prompt(items, store_id, date))))
        except Exception:
            return {}  # graceful degrade → rule baseline
        if not isinstance(parsed, dict):
            return {}
        out: Dict[str, Dict[str, Any]] = {}
        for ref_id, v in parsed.items():
            if not isinstance(v, dict):
                continue
            clean = _clean_entry(v)
            if clean is not None:
                out[str(ref_id)] = clean
        return out


def make_forecast_agent() -> Any:
    """Factory: LLM agent when HOTPOT_FORECAST=1 + key present; else rule baseline."""
    key = os.environ.get("HOTPOT_FORECAST_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    if os.environ.get("HOTPOT_FORECAST", "") == "1" and key:
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model = os.environ.get("HOTPOT_FORECAST_MODEL") or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        return LLMForecastAgent(key, base, model)
    return RuleForecastAgent()
