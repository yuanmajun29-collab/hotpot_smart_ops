#!/usr/bin/env python3
"""
CLIP 子进程客户端引擎

通过独立子进程（cwd=/tmp 绕开 hotpot platform/ 污染）运行 CLIP 模型，
stdin/stdout JSON 行协议通信，模型常驻内存。

导出 ClipClient 类，由 engines/__init__.py 注册。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional


class ClipClient:
    """管理 CLIP 子进程生命周期，通过 stdin/stdout JSON 行协议通信。"""

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._server_path = str(
            Path(__file__).resolve().parents[1] / "clip_server.py"
        )

    def _ensure_started(self):
        if self._proc is not None and self._proc.poll() is None:
            return

        self._proc = subprocess.Popen(
            [sys.executable, self._server_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd="/tmp",
            text=True,
        )
        line = self._proc.stdout.readline()
        ready = json.loads(line)
        if not ready.get("ready"):
            raise RuntimeError(f"CLIP server failed to start: {line}")

    def classify(self, image_path: str) -> Dict[str, Any]:
        self._ensure_started()
        self._proc.stdin.write(json.dumps({"image_path": image_path}) + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        return json.loads(line)

    def close(self):
        if self._proc and self._proc.poll() is None:
            self._proc.stdin.close()
            self._proc.terminate()
            self._proc.wait(timeout=5)
            self._proc = None


# ClipClient 由 engines/__init__.py 注册为 "clip" 引擎
