#!/usr/bin/env python3
"""
前厅场景推理规则 — 所有配置、阈值、类别映射、提示词、判断逻辑

此文件不含模型加载/引擎/分类器等"推理内容"，仅含"推理规则"：
  - YOLO COCO 类别映射（哪些算人/食品/饮品/餐具）
  - CLIP 语义提示词 + 标签映射
  - Plan B（纯 YOLO 规则）每桌判断逻辑
  - 告警规则、优先级映射、推荐语模板
"""

# ═══════════════════════════════════════════════════════════
# 1. YOLO COCO 类别映射
# ═══════════════════════════════════════════════════════════

CLASS_NAMES = {
    0:  "person",      39: "bottle",    41: "cup",
    44: "spoon",       45: "bowl",      47: "apple",
    48: "sandwich",    49: "orange",    50: "broccoli",
    51: "carrot",      52: "hot dog",   53: "pizza",
    54: "donut",       55: "cake",      60: "dining table",
    67: "cell phone",  73: "book",
}

FOOD_CLASSES     = {47, 48, 49, 50, 51, 52, 53, 54, 55}
DRINK_CLASSES    = {39, 40, 41}
TABLEWARE_CLASSES = {44, 45, 60}


# ═══════════════════════════════════════════════════════════
# 2. CLIP 语义提示词（三组）
# ═══════════════════════════════════════════════════════════

TABLE_STATES = [
    "customers eating hotpot at the table",
    "a messy table with leftover food and dirty dishes",
    "staff cleaning the table",
]

SERVICE_EVENTS = [
    "a waiter serving food or drinks to the table",
    "a waiter clearing dishes from the table",
    "a waiter taking orders at the table",
]

CUSTOMER_EVENTS = [
    "customers eating and chatting happily",
    "customers waving or looking around for waiter",
    "customers getting up to leave",
    "customers paying the bill",
]

# ── 提示词 → 业务标签映射 ──

TABLE_MAP = {
    "customers eating hotpot at the table":       "dining",
    "a messy table with leftover food and dirty dishes": "needs_cleaning",
    "staff cleaning the table":                   "cleaning",
}

SERVICE_MAP = {
    "a waiter serving food or drinks to the table": "serving",
    "a waiter clearing dishes from the table":      "clearing",
    "a waiter taking orders at the table":          "taking_order",
}

CUSTOMER_MAP = {
    "customers eating and chatting happily":        "eating",
    "customers waving or looking around for waiter": "calling_waiter",
    "customers getting up to leave":                "leaving",
    "customers paying the bill":                    "paying",
}


# ═══════════════════════════════════════════════════════════
# 3. Plan B — 纯 YOLO 规则推断
# ═══════════════════════════════════════════════════════════

def plan_b_status(person: int, food: int, tableware: int) -> str:
    """根据 YOLO 计数硬判决桌态"""
    if person == 0 and food == 0 and tableware == 0:
        return "empty"
    if person == 0 and tableware >= 3:
        return "needs_cleaning"
    if person == 0 and tableware <= 2 and food == 0:
        return "ready"
    if person >= 1:
        return "dining"
    return "unknown"


def plan_b_alerts(status: str, person: int, food: int, drink: int,
                  tableware: int, has_phone: bool = False,
                  **kwargs) -> list:
    """Plan B 告警规则"""
    alerts = []
    if status == "dining":
        if tableware >= 3 and food <= 1:
            alerts.append(f"empty_plate_count:{tableware}")
        if person >= 2 and drink <= 1:
            alerts.append("low_drinks")
    if status == "needs_cleaning":
        alerts.append("needs_cleaning")
    if bool(has_phone) and status == "dining":
        alerts.append("customer_ready_to_pay")
    return alerts


def plan_b_behavior(person: int, has_phone: bool = False) -> str:
    """Plan B 顾客行为推断"""
    if bool(has_phone) and person >= 1:
        return "ready_to_pay"
    if person >= 1:
        return "normal_dining"
    return "none"


# ═══════════════════════════════════════════════════════════
# 4. 优先级映射
# ═══════════════════════════════════════════════════════════

PRIORITY_MAP = {
    "needs_cleaning": "high",
    "empty":          "low",
    "dining":         "medium",
    "ready":          "medium",
}


def compute_priority(status: str, alerts: list) -> str:
    """综合状态+告警计算最终优先级"""
    if "customer_ready_to_pay" in alerts:
        return "high"
    return PRIORITY_MAP.get(status, "medium")


# ═══════════════════════════════════════════════════════════
# 5. 推荐语模板
# ═══════════════════════════════════════════════════════════

def build_recommendation(status: str, alerts: list, table_id: str) -> str:
    """根据状态+告警生成中文推荐语"""
    tid = table_id or "该桌"

    if status == "needs_cleaning":
        return f"推促清洁人员到 {tid}：需收拾清理"

    if status == "dining":
        parts = [f"推促服务员关注 {tid}"]
        if "low_drinks" in alerts:
            parts.append("加饮品")
        if any(a.startswith("empty_plate_count") for a in alerts):
            parts.append("收空盘")
        if "customer_calling" in alerts:
            parts.append("顾客呼叫")
        if "customer_ready_to_pay" in alerts:
            parts.append("准备结账")
        return (
            "：".join([parts[0], "、".join(parts[1:])])
            if len(parts) > 1 else parts[0]
        )

    if status == "ready":
        return f"{tid} 翻台就绪，可引导新客入座"

    if status == "empty":
        return f"{tid} 空桌可用"

    return f"关注 {tid}"


# ═══════════════════════════════════════════════════════════
# 6. 检测计数工具
# ═══════════════════════════════════════════════════════════

def count_detections(detections: list) -> dict:
    """从 YOLO 检测结果统计各类物体数量"""
    person = food = drink = tableware = 0
    has_phone = False

    for d in detections:
        cid = d.get("class_id", -1)
        if cid == 0:
            person += 1
        elif cid in FOOD_CLASSES:
            food += 1
        elif cid in DRINK_CLASSES:
            drink += 1
        elif cid in TABLEWARE_CLASSES:
            tableware += 1
        elif cid == 67:
            has_phone = True

    return {
        "person": person, "food": food, "drink": drink,
        "tableware": tableware, "has_phone": has_phone,
    }
