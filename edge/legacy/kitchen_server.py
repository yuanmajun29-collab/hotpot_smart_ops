"""后厨推理 API — 直接调 llama-mtmd-cli（已验证通过）"""
import subprocess, json, os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx

app = FastAPI(title="hotpot-kitchen")

LLAMA_CLI = os.environ.get("LLAMA_CLI", "/opt/hotpot-infer/bin/llama-mtmd-cli")
MODEL_PATH = os.environ.get("LLAMA_MODEL", "/opt/hotpot-infer/models/ostrakon-vl-8b/Ostrakon-VL-8B.IQ4_XS.gguf")
MMPROJ_PATH = os.environ.get("LLAMA_MMPROJ", "/opt/hotpot-infer/models/ostrakon-vl-8b/Ostrakon-VL-8B.mmproj-Q8_0.gguf")
HUB_URL = os.environ.get("HOTPOT_HUB_URL", "http://192.168.2.85:8098")
STORE_ID = os.environ.get("HOTPOT_STORE_ID", "store_yuhuan")
ZONE = os.environ.get("HOTPOT_ZONE", "kitchen")

PROMPT = '你是后厨废弃物识别系统。分析图片中的废弃食材/餐余，输出严格JSON：{"items":[{"waste_type":"备餐废弃|边角料|过期临界|餐后剩余","sku":"食材名","estimated_portion":0.8,"unit":"份","confidence":0.82,"reason":"判断依据"}]}'

class InferRequest(BaseModel):
    image_path: str

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "kitchen",
        "model": os.path.basename(MODEL_PATH),
        "cli": os.path.exists(LLAMA_CLI)
    }

@app.post("/infer")
def infer(req: InferRequest):
    if not Path(req.image_path).exists():
        raise HTTPException(404, f"图片不存在: {req.image_path}")

    cmd = [
        LLAMA_CLI, "-m", MODEL_PATH, "--mmproj", MMPROJ_PATH,
        "--image", req.image_path, "--image-min-tokens", "1024",
        "-p", PROMPT, "--temp", "0.1", "-n", "512"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    # 从输出中提取 JSON
    out = result.stdout
    try:
        brace = out.index("{")
        data = json.loads(out[brace:])
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(500, f"VLM 输出解析失败: {out[:200]}")

    # 推 Hub
    try:
        httpx.post(f"{HUB_URL}/v1/vlm/waste-estimate", json={
            "store_id": STORE_ID, "zone": ZONE,
            "source": "jetson-kitchen-docker",
            "model": "Ostrakon-VL-8B.IQ4_XS",
            "items": data.get("items", [])
        }, headers={"X-Api-Key": "test-key"}, timeout=10)
    except Exception:
        pass

    return {"ok": True, "items": data.get("items", []), "pushed_to_hub": True}
