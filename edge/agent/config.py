"""边缘 agent 统一配置常量 — 全部来自环境变量"""

import os

# ─── Hub 连接 + 设备标识 ───
HUB_URL = os.environ.get("HOTPOT_HUB_URL", "http://192.168.2.85:8098")
DEVICE_ID = os.environ.get("HOTPOT_DEVICE_ID", "jetson-yuhuan-01")
STORE_ID = os.environ.get("HOTPOT_STORE_ID", "store_yuhuan")
API_KEY = os.environ.get("HOTPOT_API_KEY", "")

# ─── 启动校验 ───
def _validate():
    """启动时强制检查关键配置。开发模式下跳过。"""
    if os.environ.get("HOTPOT_DEV_MODE", "") == "1":
        return  # 开发模式，不校验
    missing = []
    if not API_KEY or API_KEY == "test-key":
        missing.append("HOTPOT_API_KEY (禁止使用 test-key)")
    if not DEVICE_ID.startswith("jetson-") and not DEVICE_ID.startswith("rk3588-"):
        missing.append(f"HOTPOT_DEVICE_ID (当前值 '{DEVICE_ID}' 格式可疑)")
    if missing:
        raise SystemExit(
            f"❌ 配置校验失败，缺少以下环境变量:\n" +
            "\n".join(f"  - {m}" for m in missing) +
            "\n\n请在 docker-compose.yml 或 .env 中设置后重试。\n"
            "开发调试可设 HOTPOT_DEV_MODE=1 跳过校验。"
        )

_validate()

# ─── 服务端口 ───
SERVER_PORT = int(os.environ.get("HOTPOT_AGENT_PORT", "9100"))
SERVER_HOST = os.environ.get("HOTPOT_AGENT_HOST", "0.0.0.0")

# ─── 后厨推理管道 — YOLO 预过滤 + VLM（ADR-014 三级过滤） ───
# YOLO 预过滤：检测厨房场景 → 仅可疑帧触发 VLM（省 80-95% 调用）
# 设置 HOTPOT_KITCHEN_VLM_ENABLED=0 关闭 VLM 层，纯 YOLO 模式
LLAMA_CLI = os.environ.get(
    "LLAMA_CLI", "/opt/hotpot-infer/bin/llama-mtmd-cli"
)
LLAMA_MODEL = os.environ.get(
    "LLAMA_MODEL",
    "/opt/hotpot-infer/models/ostrakon-vl-8b/Ostrakon-VL-8B.IQ4_XS.gguf",
)
LLAMA_MMPROJ = os.environ.get(
    "LLAMA_MMPROJ",
    "/opt/hotpot-infer/models/ostrakon-vl-8b/Ostrakon-VL-8B.mmproj-Q8_0.gguf",
)
VLM_TIMEOUT = int(os.environ.get("VLM_TIMEOUT", "120"))

# ─── 心跳 / 配置轮询间隔 ───
HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", "30"))
CONFIG_POLL_INTERVAL = int(os.environ.get("CONFIG_POLL_INTERVAL", "60"))

# ─── 本地路径 ───
IPC_CONFIG_PATH = os.environ.get(
    "IPC_CONFIG_PATH", "/opt/hotpot-infer/config/ipc_config.yml"
)
DEVICE_CONFIG_PATH = os.environ.get(
    "DEVICE_CONFIG_PATH", "/opt/hotpot-infer/config/device_config.json"
)

# ─── 推理输出 ───
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "demo" / "data" / "edge_output"
