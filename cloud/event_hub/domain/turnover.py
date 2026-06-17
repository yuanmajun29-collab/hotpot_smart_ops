from __future__ import annotations

from typing import Any, Dict, List


def turnover_suggestions(tables: Dict[str, Dict]) -> List[Dict[str, Any]]:
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
