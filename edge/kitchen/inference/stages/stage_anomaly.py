#!/usr/bin/env python3
"""
Stage 3 — SuperADD 厨房异常检测
MobileNetV3 + Memory Bank → 零训练异常热力图
"""

import json
import subprocess
import time
from pathlib import Path

STAGE_NAME = "anomaly"
STAGE_ORDER = 3

SCRIPT = Path(__file__).resolve().parents[1] / "anomaly_infer.py"
BANK_PATH = "/opt/hotpot-infer/models/kitchen_normality_bank.npz"


def run(frame_path: str, ctx: dict) -> dict:
    """运行异常检测，结果写入 ctx["anomaly_result"]"""
    if not SCRIPT.exists():
        err = f"anomaly_infer.py not found: {SCRIPT}"
        ctx["anomaly_result"] = {"status": "error", "error": err}
        return ctx["anomaly_result"]

    if not Path(BANK_PATH).exists():
        err = f"Memory Bank not found: {BANK_PATH}"
        ctx["anomaly_result"] = {"status": "error", "error": err}
        return ctx["anomaly_result"]

    t0 = time.time()
    try:
        result = subprocess.run(
            [
                "python3",
                str(SCRIPT),
                "detect",
                frame_path,
                "--bank",
                BANK_PATH,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            cwd="/tmp",  # 避开 hotpot_platform 目录污染
        )

        if result.returncode != 0:
            ctx["anomaly_result"] = {
                "status": "error",
                "error": result.stderr.strip() or "anomaly detect failed",
            }
            return ctx["anomaly_result"]

        data = json.loads(result.stdout.split("\n")[0])  # 第一行是 JSON
        data["stage_time_ms"] = int((time.time() - t0) * 1000)
        ctx["anomaly_result"] = data
        return data

    except subprocess.TimeoutExpired:
        ctx["anomaly_result"] = {"status": "error", "error": "timeout (30s)"}
        return ctx["anomaly_result"]
    except Exception as e:
        ctx["anomaly_result"] = {"status": "error", "error": str(e)}
        return ctx["anomaly_result"]
