""" Agent 自然语言 Chat 入口 — 为展会 Demo 提供对话式 AI 助手入口。

设计目的：
    - 弥补当前缺失的 Agent 自然语言交互入口
    - 支持多 Agent 路由：根据用户意图分发到店长/后厨/采购/供应商 Agent
    - 支持 streaming 响应，适配展会大屏展示

Usage:
    POST /api/v1/agent/chat
    {"message": "帮我看看今日后厨损耗情况", "store_id": "store_yuhuan"}
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Agent Chat"])
ROUTER_TAG = "agent-chat"

# ── Pydantic Models ──────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    """Agent 对话请求。"""
    message: str = Field(..., description="用户自然语言消息")
    store_id: str = Field(default=os.environ.get("HOTPOT_STORE_ID", "store_yuhuan"), description="门店 ID")
    session_id: Optional[str] = Field(default=None, description="会话 ID，不传则新建会话")
    context: Optional[Dict[str, Any]] = Field(default=None, description="附加上下文（当前页面、选中数据等）")
    stream: bool = Field(default=False, description="是否启用流式响应")


class ChatResponse(BaseModel):
    """Agent 对话响应。"""
    session_id: str
    agent: str = Field(description="响应的 Agent 角色：store_manager/kitchen/procurement/supplier")
    message: str = Field(description="Agent 回复内容")
    actions: List[Dict[str, Any]] = Field(default_factory=list, description="建议的操作列表")
    data: Optional[Dict[str, Any]] = Field(default=None, description="附带的结构化数据（KPI、图表等）")
    timestamp: str
    tokens_used: int = 0


class ChatSession(BaseModel):
    """对话会话信息。"""
    session_id: str
    store_id: str
    messages: List[Dict[str, str]] = Field(default_factory=list)
    created_at: str
    updated_at: str


# ── Intent Router ────────────────────────────────────────────────────────────

INTENT_PATTERNS: Dict[str, List[str]] = {
    "kitchen": [
        r"(后厨|厨房|备菜|配菜|出餐|损耗|废料|浪费|食材库存|备货|准备.*菜品)",
        r"(sop|规范|操作标准|合规|违规)",
        r"(waste|kitchen|prep|cook|ingredient)",
    ],
    "procurement": [
        r"(采购|进货|订货|下单|补货|供应商|比价|价格|报价|采购单)",
        r"(收货|质检|验收|入库|品质|质量)",
        r"(procurement|purchase|order|supplier|price|quality|receiving)",
    ],
    "store_manager": [
        r"(门店|店铺|今日|昨天|本周|本月|营业额|营收|利润|成本|毛利|客流量|翻台)",
        r"(概览|汇总|总览|看板|dashboard|报告|统计|分析|趋势)",
        r"(store|revenue|profit|overview|dashboard|report)",
    ],
    "supplier": [
        r"(供应商.*管理|协同|对账|结算|评分|评价|评级|投诉|退换货)",
        r"(supplier.*manage|collaboration|settlement|rating|return)",
    ],
}


def classify_intent(message: str) -> str:
    """根据用户消息内容路由到最匹配的 Agent。

    优先级：kitchen > procurement > store_manager > supplier
    默认回退到 store_manager。
    """
    msg_lower = message.lower()

    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, msg_lower):
                return intent

    return "store_manager"


# ── Agent Handlers (stub implementations) ────────────────────────────────────

_STORE_CONTEXT = {}  # 延迟加载，见 _get_store_context()

# 简易对话模板（展会 Demo 用真数据、简易模板）
_TEMPLATES: Dict[str, Dict[str, str]] = {
    "kitchen": {
        "waste": "今日后厨损耗：废料 3.2kg（牛油底料边角料 1.5kg、菜品边角料 1.7kg），"
                 "比昨日降低 12%。建议：继续优化切配流程，预计每月可节省 ¥2,400。",
        "sop": "今日 SOP 合规率 94%，2 项违规：切配区工具未归位（轻微）、出餐口温度记录缺失（已补录）。"
               "已自动生成培训任务分配给相关员工。",
        "default": "后厨当前状态：出餐中（高峰期），当前积压 3 单。"
                    "备货充足，主要食材库存均在安全线以上。建议关注毛肚消耗速度，预计 2 小时后需要提前解冻。",
    },
    "procurement": {
        "supplier": "供应商对比：\n"
                    "1. 鑫盛食品 — 评分 A（94），毛肚报价 ¥38/kg，冻品配送准时率 99%\n"
                    "2. 华源冷链 — 评分 B+（89），毛肚报价 ¥36/kg，配送准时率 95%\n"
                    "3. 海底食品 — 评分 A-（91），毛肚报价 ¥40/kg，配送准时率 98%\n"
                    "建议：优先鑫盛食品，品质稳定且配送及时。",
        "order": "当前采购需求：系统预测明日需要补货 6 项 SKU，总预算 ¥3,840。\n"
                 "高优先级：毛肚（库存仅够 1.5 天）、鸭肠（库存仅够 2 天）。\n"
                 "已生成采购建议单 PO-20260806-001，待店长审批。",
        "default": "当前无待处理采购单。最近一批到货：今日 14:00 鑫盛食品配送，冻毛肚 50kg、冻鸭肠 30kg。",
    },
    "store_manager": {
        "overview": "今日门店经营概览：\n"
                    "• 营业额：¥28,400（达成率 94.7%）\n"
                    "• 客流量：187 桌（同比 +12%）\n"
                    "• 翻台率：2.8 次/桌\n"
                    "• 人均消费：¥152\n"
                    "• 食材成本率：32.1%（目标 ≤33%）\n"
                    "• 人工成本率：18.5%\n"
                    "AI 建议：今日达成率略低于目标，建议 18:00 开始推出限时套餐提高客单价。",
        "report": "本周趋势报告（2026-W32）：\n"
                  "• 营业额 ¥182,000（环比 +5.3%）\n"
                  "• TOP3 菜品：毛肚火锅（32%）、虾滑（18%）、雪花牛肉（15%）\n"
                  "• 食材损耗率：2.8%（环比 -0.3pp）\n"
                  "• 员工 SOP 合规率：93%（环比 +2pp）",
        "default": "门店当前状态正常。有 2 条待处理提醒：\n"
                    "1. 采购单 PO-20260806-001 待审批（过期时间：今日 18:00）\n"
                    "2. 后厨废料溢出告警（14:30 触发，已自动清理）",
    },
    "supplier": {
        "settlement": "本月对账状态：\n"
                      "• 鑫盛食品：已对账，差额 ¥0（已确认）\n"
                      "• 华源冷链：已对账，差额 ¥120（待确认：配送费差异）\n"
                      "• 海底食品：未对账，预计采购额 ¥18,400",
        "rating": "供应商评分：\n"
                  "• 鑫盛食品：94 → A 级（品质稳定）\n"
                  "• 华源冷链：89 → B+ 级（上月一次配送延迟扣分）\n"
                  "• 海底食品：91 → A- 级（价格略高，品质好）",
        "default": "供应商协同平台状态正常。\n"
                    "本月退货记录：2 笔（华源冷链冻鸭肠品质问题，已于 08-03 退回替换）。\n"
                    "未处理投诉：0 笔。",
    },
}


def _get_store_context() -> dict:
    """延迟加载门店上下文，优先从 common/env.py 获取，兜底使用 Demo 数据。"""
    global _STORE_CONTEXT
    if _STORE_CONTEXT:
        return _STORE_CONTEXT

    # 兜底 Demo 数据
    _STORE_CONTEXT = {
        "store_yuhuan": {"name": "玉环店", "daily_revenue": 28400, "tables": 42, "chefs": 6},
        "store_jiaojiang": {"name": "椒江店", "daily_revenue": 31200, "tables": 48, "chefs": 8},
    }

    # 尝试从 env.py 合并门店显示名
    try:
        from common.env import get_store_display
        for sid in list(_STORE_CONTEXT.keys()):
            _STORE_CONTEXT[sid]["name"] = get_store_display(sid)
    except ImportError:
        pass

    return _STORE_CONTEXT


def _pick_template(intent: str, message: str) -> str:
    """根据用戶消息匹配最合适的回复模板。"""
    templates = _TEMPLATES.get(intent, {})
    msg_lower = message.lower()

    if intent == "kitchen":
        if any(kw in msg_lower for kw in ["损耗", "废料", "浪费", "waste"]):
            return templates.get("waste", templates["default"])
        if any(kw in msg_lower for kw in ["sop", "规范", "合规", "违规"]):
            return templates.get("sop", templates["default"])
    elif intent == "procurement":
        if any(kw in msg_lower for kw in ["供应商", "比价", "supplier"]):
            return templates.get("supplier", templates["default"])
        if any(kw in msg_lower for kw in ["采购", "订货", "下单", "order"]):
            return templates.get("order", templates["default"])
    elif intent == "store_manager":
        if any(kw in msg_lower for kw in ["今日", "今天", "概览", "看板", "dashboard", "今日门店"]):
            return templates.get("overview", templates["default"])
        if any(kw in msg_lower for kw in ["本周", "报告", "趋势", "report", "周报"]):
            return templates.get("report", templates["default"])
    elif intent == "supplier":
        if any(kw in msg_lower for kw in ["对账", "结算", "settlement"]):
            return templates.get("settlement", templates["default"])
        if any(kw in msg_lower for kw in ["评分", "评级", "rating"]):
            return templates.get("rating", templates["default"])

    return templates.get("default", f"收到：{message[:30]}...")


def _generate_actions(intent: str, message: str) -> list:
    """根据意图生成建议操作。"""
    msg_lower = message.lower()
    actions = []

    if intent == "procurement":
        if any(kw in msg_lower for kw in ["下单", "采购", "订货"]):
            actions = [
                {"type": "view", "label": "查看采购建议单", "route": "/supply-chain/procurement"},
                {"type": "action", "label": "一键下单", "action": "create_po_from_suggestion"},
                {"type": "view", "label": "查看供应商对比", "route": "/supply-chain/suppliers/compare"},
            ]
        else:
            actions = [
                {"type": "view", "label": "进入采购管理", "route": "/supply-chain/procurement"},
            ]
    elif intent == "kitchen":
        actions = [
            {"type": "view", "label": "查看后厨实时画面", "route": "/kitchen/live"},
            {"type": "view", "label": "今日损耗详情", "route": "/kitchen/waste"},
            {"type": "action", "label": "生成备货建议", "action": "generate_prep_suggestion"},
        ]
    elif intent == "store_manager":
        actions = [
            {"type": "view", "label": "打开门店看板", "route": "/store/dashboard"},
            {"type": "view", "label": "查看详细报表", "route": "/store/reports"},
        ]
    elif intent == "supplier":
        actions = [
            {"type": "view", "label": "进入供应商管理", "route": "/supply-chain/suppliers"},
            {"type": "view", "label": "查看对账详情", "route": "/supply-chain/settlement"},
        ]

    return actions


# ── Session Management (in-memory) ───────────────────────────────────────────

_sessions: Dict[str, ChatSession] = {}


def _get_or_create_session(store_id: str, session_id: Optional[str] = None) -> ChatSession:
    """获取或创建会话。"""
    ts = _now()
    if session_id and session_id in _sessions:
        session = _sessions[session_id]
        session.updated_at = ts
        return session

    sid = session_id or f"sess_{int(time.time() * 1000)}"
    session = ChatSession(
        session_id=sid,
        store_id=store_id,
        messages=[],
        created_at=ts,
        updated_at=ts,
    )
    _sessions[sid] = session
    return session


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ── API Endpoints ────────────────────────────────────────────────────────────

@router.post("/api/v1/agent/chat", response_model=ChatResponse,
             summary="Agent 自然语言对话",
             description="接收用户自然语言消息，自动路由到对应岗位 Agent 并返回回复。")
async def agent_chat(request: ChatRequest) -> ChatResponse:
    """Agent 对话入口。

    流程：
    1. 意图识别 → 路由到对应 Agent
    2. 生成模板化回复（Demo 阶段）+ 建议操作
    3. 返回 ChatResponse
    """
    if not request.message or not request.message.strip():
        raise HTTPException(status_code=400, detail="message 不能为空")

    intent = classify_intent(request.message)
    agent_name_map = {
        "kitchen": "kitchen_agent",
        "procurement": "procurement_agent",
        "store_manager": "store_manager_agent",
        "supplier": "supplier_agent",
    }
    agent = agent_name_map.get(intent, "store_manager_agent")

    # Session management
    session = _get_or_create_session(request.store_id, request.session_id)

    # Generate response
    reply = _pick_template(intent, request.message)
    actions = _generate_actions(intent, request.message)

    # Record message
    session.messages.append({"role": "user", "content": request.message, "time": _now()})
    session.messages.append({"role": "assistant", "content": reply, "time": _now(), "agent": agent})

    # Contextual data
    data = {"intent": intent, "store": _get_store_context().get(request.store_id, {})}

    return ChatResponse(
        session_id=session.session_id,
        agent=agent,
        message=reply,
        actions=actions,
        data=data,
        timestamp=_now(),
        tokens_used=len(request.message) + len(reply),
    )


@router.get("/api/v1/agent/sessions/{store_id}",
            summary="获取门店对话历史",
            response_model=List[ChatSession])
async def list_sessions(store_id: str):
    """获取指定门店的所有对话会话。"""
    return [s for s in _sessions.values() if s.store_id == store_id]


@router.get("/api/v1/agent/sessions/{store_id}/{session_id}",
            summary="获取指定会话详情",
            response_model=ChatSession)
async def get_session(store_id: str, session_id: str):
    """获取指定会话详情。"""
    session = _sessions.get(session_id)
    if not session or session.store_id != store_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


@router.delete("/api/v1/agent/sessions/{store_id}/{session_id}",
               summary="删除对话会话")
async def delete_session(store_id: str, session_id: str):
    """删除指定会话。"""
    session = _sessions.get(session_id)
    if not session or session.store_id != store_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    del _sessions[session_id]
    return {"ok": True, "deleted": session_id}
