#!/usr/bin/env python3
"""VLM Inference Wrapper — Ostrakon-VL 后厨场景分析

推理规则（提示词/阈值）→ rules.py
推理内容（llama.cpp 调用/解析）→ 本文件

Calls llama.cpp's llama-mtmd-cli with the Ostrakon-VL-8B model.
Outputs structured JSON for Hub ingestion.

Usage:
    python3 vlm_infer.py --image /tmp/roi.jpg --zone "备餐废弃区"
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from .rules import KITCHEN_PROMPT, VLM_TIMEOUT_SEC, VLM_TEMPERATURE, VLM_MAX_TOKENS

# Default paths (overridable via args)
LLAMA_CLI = "/opt/hotpot-infer/bin/llama-mtmd-cli"
MODEL_PATH = "/opt/hotpot-infer/models/ostrakon-vl-8b/Ostrakon-VL-8B.IQ4_XS.gguf"
MMPROJ_PATH = "/opt/hotpot-infer/models/ostrakon-vl-8b/Ostrakon-VL-8B.mmproj-Q8_0.gguf"

# KITCHEN_PROMPT 已移至 rules.py


def run_vlm(image_path: str, zone: str, timeout: int = VLM_TIMEOUT_SEC) -> dict:
    """Run Ostrakon-VL inference, parse JSON output."""
    if not Path(LLAMA_CLI).exists():
        return {"error": f"llama-llava-cli not found at {LLAMA_CLI}"}
    if not Path(MODEL_PATH).exists():
        return {"error": f"Model not found at {MODEL_PATH}"}

    t0 = time.time()

    cmd = [
        LLAMA_CLI,
        "-m", MODEL_PATH,
        "--mmproj", MMPROJ_PATH,
        "--image", image_path,
        "-p", KITCHEN_PROMPT,
        "--temp", str(VLM_TEMPERATURE),
        "-n", str(VLM_MAX_TOKENS),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        dt = (time.time() - t0) * 1000
        raw_output = result.stdout.strip()

        # Try to extract JSON from output (llama.cpp may add prefixes)
        json_str = raw_output
        if "{" in json_str:
            json_str = json_str[json_str.find("{"):]
        if "}" in json_str:
            json_str = json_str[:json_str.rfind("}") + 1]

        parsed = json.loads(json_str)
        parsed["inference_ms"] = round(dt, 1)
        parsed["zone"] = zone
        parsed["model"] = "ostrakon-vl-8b-iq4xs"
        parsed["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        return parsed

    except subprocess.TimeoutExpired:
        return {"error": f"VLM inference timeout ({timeout}s)", "inference_ms": timeout * 1000}
    except json.JSONDecodeError:
        return {
            "error": "Failed to parse VLM output as JSON",
            "raw_output": raw_output[:500],
            "inference_ms": round((time.time() - t0) * 1000, 1),
        }


def main():
    parser = argparse.ArgumentParser(description="VLM Inference (Ostrakon-VL)")
    parser.add_argument("--image", required=True)
    parser.add_argument("--zone", default="备餐废弃区")
    parser.add_argument("--timeout", type=int, default=VLM_TIMEOUT_SEC)
    args = parser.parse_args()

    result = run_vlm(args.image, args.zone, args.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if "error" in result:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
