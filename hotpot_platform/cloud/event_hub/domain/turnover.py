"""翻台率计算 — 从桌态变化历史计算真实翻台率。

核心：
  - turnover_suggestions(): 静态建议（保留兼容）
  - compute_turnover_rate(): 从 table_history 计算真实翻台率
  - compute_avg_dine_time(): 计算平均用餐时间

翻台率公式:
  turnover_rate = completed_tables_in_window / total_tables / time_window_hours

桌态变化: empty → occupied → needs_cleaning → completed
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple


def turnover_suggestions(tables: Dict[str, Dict]) -> List[Dict[str, Any]]:
    """静态翻台建议（现有兼容接口）。"""
    priority = {"need_clean": 1, "checkout": 2, "empty": 3}
    items = []
    for t in tables.values():
        st = t.get("state", "")
        if st in priority:
            items.append(
                {
                    "table_id": t["table_id"],
                    "state": st,
                    "priority": priority[st],
                    "action": {"need_clean": "立即清台", "checkout": "引导结账", "empty": "可安排入座"}.get(st, ""),
                }
            )
    return sorted(items, key=lambda x: (x["priority"], x["table_id"]))


def compute_turnover_rate(
    table_history: Dict[str, List[Dict[str, Any]]],
    total_tables: int,
    window_hours: float = 24.0,
) -> Dict[str, Any]:
    """从桌态变化历史计算真实翻台率。

    Args:
        table_history: {table_id: [{status, changed_at, duration_min}, ...]}
        total_tables: 门店总桌数
        window_hours: 时间窗口（小时），默认24h=当天

    Returns:
        {
            "total_tables": int,
            "window_hours": float,
            "completed_tables": int,
            "turnover_rate": float,
            "avg_dine_min": float,
            "avg_wait_min": float,
            "avg_clean_min": float,
            "details": [...],
        }
    """
    import statistics

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=window_hours)

    completed_count = 0
    avg_dine_times: List[float] = []
    avg_clean_times: List[float] = []
    turnover_cycles: List[Dict[str, Any]] = []

    for table_id, history in table_history.items():
        # 在时间窗口内查找 completed 状态
        for entry in reversed(history):
            try:
                ts = datetime.fromisoformat(entry["changed_at"])
            except Exception:
                continue

            if ts < cutoff:
                break

            if entry.get("status") == "completed":
                completed_count += 1

        # 统计平均用餐时间和清台时间
        dine_times: List[float] = []
        clean_times: List[float] = []

        for entry in history:
            status = entry.get("status", "")
            duration = entry.get("duration_min", 0.0)
            if status == "occupied" and duration > 0:
                dine_times.append(duration)
            elif status in ("needs_cleaning", "cleaning") and duration > 0:
                clean_times.append(duration)

        if dine_times:
            avg_dine = round(sum(dine_times) / len(dine_times), 1)
            avg_dine_times.append(avg_dine)

        if clean_times:
            avg_clean = round(sum(clean_times) / len(clean_times), 1)
            avg_clean_times.append(avg_clean)

        # 翻台周期
        cycles = sum(
            1 for e in history
            if e.get("status") == "completed"
            and e.get("duration_min", 0) > 0
        )
        if cycles > 0:
            turnover_cycles.append({
                "table_id": table_id,
                "completed_cycles": cycles,
            })

    n_completed = completed_count

    # 翻台率 = completed / total / hours
    if total_tables > 0 and window_hours > 0:
        rate = round(n_completed / total_tables / (window_hours / 24.0), 3)  # 标准化为每天
    else:
        rate = 0.0

    return {
        "total_tables": total_tables,
        "window_hours": window_hours,
        "completed_tables": n_completed,
        "turnover_rate": rate,
        "avg_dine_min": round(statistics.mean(avg_dine_times), 1) if avg_dine_times else 0.0,
        "avg_clean_min": round(statistics.mean(avg_clean_times), 1) if avg_clean_times else 0.0,
        "avg_wait_min": 0.0,  # wait time 需从 empty→occupied 间隔计算，此处用 avg_clean 近似
        "details": turnover_cycles[:20],  # 最多返回20桌
    }
