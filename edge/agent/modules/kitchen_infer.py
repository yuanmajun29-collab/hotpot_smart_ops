"""后厨 VLM 推理模块 — llama-mtmd-cli 调用 + 推 Hub

移自 edge/kitchen/server.py。通过 _active 标志由 server.py 按 zone 激活。
"""

import subprocess
import json
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from edge.agent.config import (
    LLAMA_CLI, LLAMA_MODEL, LLAMA_MMPROJ, VLM_TIMEOUT,
    HUB_URL, STORE_ID, API_KEY,
)

router = APIRouter(prefix="/infer", tags=["kitchen"])

# 由 server.py 在配置驱动下设置
_active = False
_zone = "kitchen"

PROMPT = (
    '你是后厨废弃物识别系统。分析图片中的废弃食材/餐余，输出严格JSON：'
    '{"items":[{"waste_type":"备餐废弃|边角料|过期临界|餐后剩余",'
    '"sku":"食材名","estimated_portion":0.8,"unit":"份",'
    '"confidence":0.82,"reason":"判断依据"}]}'
)


class InferRequest(BaseModel):
    image_path: str


def _check_active():
    if not _active:
        raise HTTPException(503, "kitchen 模块未激活（配置中无 kitchen zone）")


@router.get("/kitchen/health")
def kitchen_health():
    return {
        "module": "kitchen",
        "active": _active,
        "zone": _zone,
        "cli_exists": Path(LLAMA_CLI).exists(),
        "model": Path(LLAMA_MODEL).name if LLAMA_MODEL else "N/A",
    }


@router.post("/kitchen")
def kitchen_infer(req: InferRequest):
    """VLM 废弃物识别"""
    _check_active()

    img_path = Path(req.image_path)
    if not img_path.exists():
        raise HTTPException(404, f"图片不存在: {req.image_path}")

    cmd = [
        LLAMA_CLI, "-m", LLAMA_MODEL, "--mmproj", LLAMA_MMPROJ,
        "--image", str(img_path), "--image-min-tokens", "1024",
        "-p", PROMPT, "--temp", "0.1", "-n", "512",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=VLM_TIMEOUT)

    # 从输出提取 JSON
    out = result.stdout
    try:
        brace = out.index("{")
        data = json.loads(out[brace:])
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(500, f"VLM 输出解析失败: {out[:200]}")

    # 推 Hub
    pushed = False
    try:
        httpx.post(
            f"{HUB_URL}/v1/vlm/waste-estimate",
            json={
                "store_id": STORE_ID,
                "zone": _zone,
                "source": "jetson-agent-kitchen",
                "model": "Ostrakon-VL-8B.IQ4_XS",
                "items": data.get("items", []),
            },
            headers={"X-Api-Key": API_KEY},
            timeout=10,
        )
        pushed = True
    except Exception:
        pass

    return {"ok": True, "items": data.get("items", []), "pushed_to_hub": pushed}
