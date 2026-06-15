"""VLM review API — quality grade, table clean readiness (DEV-301)."""

from __future__ import annotations

import base64
import json
import os
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="Hotpot VLM Review", version="1.0.0")


class ReviewRequest(BaseModel):
    event_type: str = ""
    image_path: str = ""
    image_base64: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class QualityGradeRequest(BaseModel):
    sku: str = ""
    batch_id: str = ""
    image_path: str = ""
    image_base64: str = ""


class TableCleanRequest(BaseModel):
    table_id: str = ""
    image_path: str = ""
    image_base64: str = ""


def _load_image_b64(req_path: str, req_b64: str) -> Optional[str]:
    if req_b64:
        return req_b64
    if req_path and Path(req_path).exists():
        return base64.b64encode(Path(req_path).read_bytes()).decode()
    return None


def _rule_review(event_type: str) -> Dict[str, Any]:
    confirmed = event_type in (
        "kitchen_smoke",
        "cold_chain_high",
        "table_need_clean",
        "cost_quality_reject",
    )
    return {
        "confirmed": confirmed,
        "confidence": 0.85 if confirmed else 0.45,
        "review_note": "规则复核（无 VLM API Key）",
        "backend": "rule",
    }


def _rule_quality_grade(sku: str) -> Dict[str, Any]:
    grade = "B"
    if "毛肚" in sku or "鲜" in sku:
        grade = "A"
    return {
        "quality_grade": grade,
        "confidence": 0.7,
        "defects": [] if grade == "A" else ["外观一般，建议厨师长复核"],
        "backend": "rule",
    }


def _rule_table_clean(table_id: str) -> Dict[str, Any]:
    seed = sum(ord(c) for c in table_id) % 3
    scores = [0.92, 0.65, 0.4]
    score = scores[seed]
    return {
        "table_id": table_id,
        "clean_ready_score": score,
        "ready": score >= 0.8,
        "residue": "无" if score >= 0.8 else "可能有锅具/杂物残留",
        "backend": "rule",
    }


def _openai_vision(prompt: str, image_b64: str, mime: str = "image/jpeg") -> str:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("OPENAI_VLM_MODEL", os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                ],
            }
        ],
        "temperature": 0.2,
        "max_tokens": 500,
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    return data["choices"][0]["message"]["content"]


def _parse_json_from_llm(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "vlm_available": bool(os.environ.get("OPENAI_API_KEY")),
        "model": os.environ.get("OPENAI_VLM_MODEL", "gpt-4o-mini"),
    }


@app.post("/review")
def review(body: ReviewRequest) -> Dict[str, Any]:
    b64 = _load_image_b64(body.image_path, body.image_base64)
    if b64 and os.environ.get("OPENAI_API_KEY"):
        try:
            prompt = (
                f"你是火锅门店视觉复核助手。事件类型：{body.event_type}。"
                "返回 JSON：{\"confirmed\": bool, \"confidence\": 0-1, \"review_note\": str}"
            )
            parsed = _parse_json_from_llm(_openai_vision(prompt, b64))
            parsed["backend"] = "openai"
            parsed["event_type"] = body.event_type
            return parsed
        except Exception as exc:
            out = _rule_review(body.event_type)
            out["review_note"] = f"VLM 失败回退规则: {exc}"
            return out
    out = _rule_review(body.event_type)
    out["event_type"] = body.event_type
    out["payload"] = body.metadata
    return out


@app.post("/quality-grade")
def quality_grade(body: QualityGradeRequest) -> Dict[str, Any]:
    b64 = _load_image_b64(body.image_path, body.image_base64)
    if b64 and os.environ.get("OPENAI_API_KEY"):
        try:
            prompt = (
                f"你是火锅食材质检员。SKU：{body.sku}，批次：{body.batch_id}。"
                "根据图片评估外观品质，返回 JSON："
                "{\"quality_grade\":\"A|B|C\", \"confidence\":0-1, \"defects\":[str]}"
            )
            parsed = _parse_json_from_llm(_openai_vision(prompt, b64))
            parsed["backend"] = "openai"
            parsed["sku"] = body.sku
            parsed["batch_id"] = body.batch_id
            return parsed
        except Exception as exc:
            out = _rule_quality_grade(body.sku)
            out["error"] = str(exc)
            return out
    out = _rule_quality_grade(body.sku)
    out["sku"] = body.sku
    out["batch_id"] = body.batch_id
    return out


@app.post("/table-clean-ready")
def table_clean_ready(body: TableCleanRequest) -> Dict[str, Any]:
    b64 = _load_image_b64(body.image_path, body.image_base64)
    if b64 and os.environ.get("OPENAI_API_KEY"):
        try:
            prompt = (
                f"评估火锅桌 {body.table_id} 是否清台完成可接下一桌。"
                "返回 JSON：{\"clean_ready_score\":0-1, \"ready\":bool, \"residue\":str}"
            )
            parsed = _parse_json_from_llm(_openai_vision(prompt, b64))
            parsed["backend"] = "openai"
            parsed["table_id"] = body.table_id
            return parsed
        except Exception as exc:
            out = _rule_table_clean(body.table_id)
            out["error"] = str(exc)
            return out
    return _rule_table_clean(body.table_id)
