#!/usr/bin/env python3
"""误报/漏报反馈 API — 样本回流 → Memory Bank 更新

端点:
  POST /v1/feedback        — 提交误报/漏报反馈
  GET  /v1/feedback         — 查询反馈列表
  GET  /v1/feedback/stats   — 反馈统计
  POST /v1/feedback/rebuild — 触发 Memory Bank 重建
"""

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from hotpot_platform.cloud.event_hub.auth import get_auth_context, AuthContext

router = APIRouter(prefix="/v1/feedback", tags=["feedback"])

FEEDBACK_DIR = Path(os.environ.get("HOTPOT_FEEDBACK_DIR", "/tmp/hotpot_feedback"))
FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)

FEEDBACK_FILE = FEEDBACK_DIR / "feedback.jsonl"
SAMPLE_DIR = FEEDBACK_DIR / "samples"
SAMPLE_DIR.mkdir(exist_ok=True)

BANK_REBUILD_SCRIPT = Path("/opt/hotpot-infer/scripts/rebuild_memory_bank.sh")


class FeedbackSubmit(BaseModel):
    image_id: str          # 推理结果ID
    event_type: str        # false_positive | false_negative | correct
    label: str = ""        # 正确标签（漏报时填写）
    bbox: List[float] = [] # [x1,y1,x2,y2]
    note: str = ""         # 备注
    zone: str = "备餐废弃区"
    store_id: str = "store_yuhuan"
    image_path: str = ""   # 原始图片路径


def _append_feedback(data: dict):
    with open(FEEDBACK_FILE, "a") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")


@router.post("")
async def submit_feedback(body: FeedbackSubmit, auth: AuthContext = Depends(get_auth_context)):
    record = {
        "id": f"fb_{int(time.time()*1000)}",
        "image_id": body.image_id,
        "event_type": body.event_type,
        "label": body.label,
        "bbox": body.bbox,
        "note": body.note,
        "zone": body.zone,
        "store_id": body.store_id,
        "image_path": body.image_path,
        "submitted_by": auth.sub,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }
    _append_feedback(record)

    # 如果有图片路径，复制样本
    if body.image_path and Path(body.image_path).exists():
        import shutil
        dst = SAMPLE_DIR / f"{record['id']}_{body.event_type}.jpg"
        shutil.copy(body.image_path, dst)
        record["sample_path"] = str(dst)

    return {"status": "ok", "id": record["id"]}


@router.get("")
async def list_feedback(limit: int = 50, event_type: str = ""):
    items = []
    if FEEDBACK_FILE.exists():
        for line in open(FEEDBACK_FILE):
            r = json.loads(line)
            if event_type and r.get("event_type") != event_type:
                continue
            items.append(r)
    items.sort(key=lambda x: x.get("submitted_at", ""), reverse=True)
    return {"feedback": items[:limit], "total": len(items)}


@router.get("/stats")
async def feedback_stats():
    stats = {"false_positive": 0, "false_negative": 0, "correct": 0, "total": 0, "last_30d": {}}
    if FEEDBACK_FILE.exists():
        cutoff = time.time() - 30*86400
        for line in open(FEEDBACK_FILE):
            r = json.loads(line)
            stats["total"] += 1
            t = r.get("event_type", "")
            if t in stats:
                stats[t] += 1
            # 30天统计
            try:
                ts = datetime.fromisoformat(r["submitted_at"]).timestamp()
            except Exception:
                ts = 0
            if ts > cutoff:
                d = datetime.fromisoformat(r["submitted_at"]).strftime("%Y-%m-%d")
                stats["last_30d"].setdefault(d, 0)
                stats["last_30d"][d] += 1
    return {"stats": stats, "samples_dir": str(SAMPLE_DIR)}


@router.post("/rebuild")
async def rebuild_memory_bank(auth: AuthContext = Depends(get_auth_context)):
    """基于反馈样本重建 Memory Bank."""
    samples = list(SAMPLE_DIR.glob("*.jpg"))
    if len(samples) < 5:
        return {"status": "skipped", "reason": f"样本不足({len(samples)}), 需>=5个"}

    # 统计有效正样本
    correct = 0
    if FEEDBACK_FILE.exists():
        for line in open(FEEDBACK_FILE):
            r = json.loads(line)
            if r.get("event_type") == "correct":
                correct += 1

    if correct < 3:
        return {"status": "skipped", "reason": f"正确样本不足({correct}), 需>=3个"}

    if BANK_REBUILD_SCRIPT.exists():
        result = subprocess.run(
            ["bash", str(BANK_REBUILD_SCRIPT), str(SAMPLE_DIR)],
            capture_output=True, text=True, timeout=300,
        )
        return {"status": "ok" if result.returncode == 0 else "error", "output": result.stdout[-500:]}
    else:
        return {"status": "skipped", "reason": "重建脚本未部署"}


@router.get("/accuracy")
async def accuracy_trend():
    """计算误报率趋势."""
    stats = []
    if FEEDBACK_FILE.exists():
        for line in open(FEEDBACK_FILE):
            r = json.loads(line)
            try:
                day = datetime.fromisoformat(r["submitted_at"]).strftime("%m-%d")
            except Exception:
                continue
            stats.append({"day": day, "type": r.get("event_type", "")})

    # 按天聚合
    days = {}
    for s in stats:
        days.setdefault(s["day"], {"total": 0, "fp": 0, "fn": 0})
        days[s["day"]]["total"] += 1
        if s["type"] == "false_positive":
            days[s["day"]]["fp"] += 1
        if s["type"] == "false_negative":
            days[s["day"]]["fn"] += 1

    trend = []
    for day in sorted(days)[-14:]:
        d = days[day]
        fp_rate = round(d["fp"] / d["total"] * 100, 1) if d["total"] else 0
        fn_rate = round(d["fn"] / d["total"] * 100, 1) if d["total"] else 0
        trend.append({"day": day, "total": d["total"], "fp_rate": fp_rate, "fn_rate": fn_rate, "accuracy": round(100 - fp_rate - fn_rate, 1)})

    return {"trend": trend}
