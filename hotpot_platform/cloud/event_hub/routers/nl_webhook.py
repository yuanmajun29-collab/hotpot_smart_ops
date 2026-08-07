"""
Agent NL Webhook — 微信消息入口
POST /webhook/nl → 规则引擎 → 回复
"""

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional
import hashlib
import os

from ..nl_router import process_message

router = APIRouter(prefix="/webhook", tags=["NL Webhook"])

WECHAT_TOKEN = os.environ.get("WECHAT_CALLBACK_TOKEN", "hotpot-nl-mvp")


class NLRequest(BaseModel):
    from_user: str
    text: str
    timestamp: Optional[int] = None
    store_id: Optional[str] = None


class NLResponse(BaseModel):
    intent: str
    matched_keyword: Optional[str] = None
    reply: str
    push_target: Optional[str] = None
    data: dict = {}


@router.post("/nl", response_model=NLResponse)
async def nl_webhook(req: NLRequest):
    """接收微信文本消息，规则匹配后返回回复"""
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="text is required")

    result = process_message(req.text, req.store_id or os.environ.get("HOTPOT_STORE_ID", ""))
    return NLResponse(**result)


@router.get("/nl/health")
async def nl_health():
    return {"status": "ok", "engine": "keyword-rule", "version": "mvp-v0.1"}
