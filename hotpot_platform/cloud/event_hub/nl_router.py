"""
Agent NL 规则引擎 — 展前MVP
关键词匹配 → 意图识别 → 数据查询 → 模板渲染
展会后升级为 LLM Agent
"""

from datetime import datetime
from typing import Optional

# === 关键词→意图映射 ===
KEYWORD_INTENTS = [
    (["损耗", "废料", "浪费"], "query_waste", "A02"),
    (["翻台", "桌态", "上座"], "query_turnover", "A01"),
    (["温度", "冷柜", "报警", "IoT"], "query_iot", "A02"),
    (["日报", "报告"], "query_daily_report", "A01"),
    (["库存", "备货"], "query_inventory", "A02"),
    (["SOP", "合规", "违规"], "query_sop", "A02"),
]


def match_intent(text: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """关键词匹配，返回 (intent, assistant_id, matched_keyword)"""
    text_lower = text.lower()
    for keywords, intent, target in KEYWORD_INTENTS:
        for kw in keywords:
            if kw.lower() in text_lower:
                return intent, target, kw
    return None, None, None


def query_data(intent: str, store_id: str = "") -> dict:
    """根据意图查询数据（MVP阶段返回模拟数据，展后接真实DB）"""
    import os as _os
    sid = store_id or _os.environ.get("HOTPOT_STORE_ID", "")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    queries = {
        "query_waste": {
            "waste_count": 3,
            "waste_amount": 156,
            "trend_pct": -12,
            "trend_icon": "↓",
        },
        "query_turnover": {
            "turnover_rate": "2.8",
            "table_count": 8,
            "occupied": 6,
            "trend_icon": "↑",
            "trend_pct": 5,
        },
        "query_iot": {
            "alert_count": 1,
            "alerts": [{"sensor": "冷柜#1", "temp": "8.5°C", "threshold": "4°C"}],
        },
        "query_daily_report": {
            "turnover_rate": "2.8",
            "waste_amount": 156,
            "alert_count": 1,
            "sop_score": 87,
        },
        "query_inventory": {
            "items_low": ["毛肚(剩2份)", "鸭肠(剩1份)"],
            "items_ok": 24,
        },
        "query_sop": {
            "score": 87,
            "violations": 2,
            "top_issue": "砧板未消毒",
        },
    }

    data = queries.get(intent, {})
    store_name = _os.environ.get("HOTPOT_STORE_NAME", data.get("store_name", ""))
    data["store_name"] = store_name or "门店"
    data["timestamp"] = now
    return data


def render_template(intent: str, data: dict) -> str:
    """模板渲染"""
    templates = {
        "query_waste": (
            "📊 {store_name} 今日损耗\n"
            "废料检测: {waste_count} 盘\n"
            "预估金额: ¥{waste_amount}\n"
            "趋势: {trend_icon}{trend_pct}% vs 昨日\n"
            "📍 {timestamp}"
        ),
        "query_turnover": (
            "🪑 {store_name} 当前桌态\n"
            "翻台率: {turnover_rate} 轮\n"
            "在用/总桌: {occupied}/{table_count}\n"
            "趋势: {trend_icon}{trend_pct}% vs 昨日\n"
            "📍 {timestamp}"
        ),
        "query_iot": (
            "🌡️ {store_name} IoT告警\n"
            "当前告警: {alert_count} 条\n"
            "📍 {timestamp}"
        ),
        "query_daily_report": (
            "📋 {store_name} 运营日报\n"
            "翻台率: {turnover_rate}\n"
            "损耗: ¥{waste_amount}\n"
            "IoT告警: {alert_count}条\n"
            "SOP评分: {sop_score}分\n"
            "📍 {timestamp}"
        ),
        "query_inventory": (
            "📦 {store_name} 库存快照\n"
            "正常品类: {items_ok} 项\n"
            "📍 {timestamp}"
        ),
        "query_sop": (
            "✅ {store_name} SOP评分\n"
            "今日得分: {score}分\n"
            "违规次数: {violations}次\n"
            "📍 {timestamp}"
        ),
        "unknown": (
            "🤔 没太明白，试试这些关键词：\n"
            "· 损耗 / 废料\n· 翻台 / 桌态\n"
            "· 温度 / 报警\n· 日报\n· 库存\n· SOP"
        ),
    }

    template = templates.get(intent, templates["unknown"])
    return template.format(**data)


def process_message(text: str, store_id: str = "") -> dict:
    """完整处理流程：匹配→查询→渲染"""
    import os as _os
    sid = store_id or _os.environ.get("HOTPOT_STORE_ID", "")
    intent, target, keyword = match_intent(text)

    if intent is None:
        return {
            "intent": "unknown",
            "matched_keyword": None,
            "reply": render_template("unknown", {}),
            "push_target": None,
            "data": {},
        }

    data = query_data(intent, sid)
    reply = render_template(intent, data)

    return {
        "intent": intent,
        "matched_keyword": keyword,
        "reply": reply,
        "push_target": target,
        "data": data,
    }
