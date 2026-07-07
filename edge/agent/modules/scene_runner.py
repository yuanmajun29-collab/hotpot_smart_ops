#!/usr/bin/env python3
"""场景分析调用器 — 从干净环境启动，绕过 platform 污染"""

import subprocess, sys, json, base64
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "front_hall" / "inference" / "scene_analyzer.py"
PROJECT = Path(__file__).resolve().parents[2]

def analyze(image_path: str, table_id: str = "") -> dict:
    """调用 scene_analyzer 子进程分析单张图片"""
    result = subprocess.run(
        [sys.executable, "-S", str(SCRIPT), image_path, table_id],
        capture_output=True, text=True, timeout=30,
        cwd=str(PROJECT),
        env={**__import__('os').environ, "PYTHONPATH": str(PROJECT)},
    )
    if result.returncode != 0:
        return {"error": result.stderr.strip()}
    return json.loads(result.stdout)

if __name__ == "__main__":
    # CLI 模式：python3 scene_runner.py <image_path> [table_id]
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: scene_runner.py <image_path> [table_id]"}))
        sys.exit(1)
    result = analyze(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
    print(json.dumps(result, ensure_ascii=False, indent=2))
