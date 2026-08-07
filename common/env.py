"""环境配置辅助 — 统一管理门店ID、网络端点等运行时常量，消除硬编码。

Usage:
    from common.env import get_store_id, get_hub_url, get_default_api_key, HOTPOT_ENV

    store_id = get_store_id("store_yuhuan")
    hub_url  = get_hub_url()
"""

from __future__ import annotations

import os
from typing import Optional

# ── 环境标识 ──────────────────────────────────────────────────────────────────

HOTPOT_ENV: str = os.environ.get("HOTPOT_ENV", "development")

ENV_DEVELOPMENT = "development"
ENV_STAGING = "staging"
ENV_PRODUCTION = "production"


def is_production() -> bool:
    """是否处于生产环境。"""
    return HOTPOT_ENV == ENV_PRODUCTION


def require_not_production(msg: str = "该操作在生产环境被禁止") -> None:
    """生产环境防护：在 production 下抛出 RuntimeError。"""
    if is_production():
        raise RuntimeError(f"[{ENV_PRODUCTION}] {msg}")


# ── 网络端点 ──────────────────────────────────────────────────────────────────

DEFAULT_HUB_HOST: str = os.environ.get("HOTPOT_HUB_HOST", "127.0.0.1")
DEFAULT_HUB_PORT: str = os.environ.get("HOTPOT_HUB_PORT", "8098")
DEFAULT_MQTT_HOST: str = os.environ.get("HOTPOT_MQTT_HOST", "127.0.0.1")
DEFAULT_MQTT_PORT: str = os.environ.get("HOTPOT_MQTT_PORT", "1883")


def get_hub_url() -> str:
    """返回 Event Hub 的完整 URL，优先使用 HOTPOT_HUB_URL 环境变量。"""
    hook = os.environ.get("HOTPOT_HUB_URL", "")
    if hook:
        return hook.rstrip("/")
    return f"http://{DEFAULT_HUB_HOST}:{DEFAULT_HUB_PORT}"


# ── 门店标识 ──────────────────────────────────────────────────────────────────

DEFAULT_STORE_ID: str = os.environ.get("HOTPOT_STORE_ID", "store_yuhuan")
TRUSTED_STORE_IDS: list[str] = [
    sid.strip()
    for sid in os.environ.get("HOTPOT_STORE_IDS", "").split(",")
    if sid.strip()
] or ["store_yuhuan", "store_jiaojiang"]


def get_store_id(default: Optional[str] = None) -> str:
    """返回当前门店 ID，可通过 HOTPOT_STORE_ID 环境变量覆盖。"""
    return os.environ.get("HOTPOT_STORE_ID", default or DEFAULT_STORE_ID)


# ── API 密钥 ──────────────────────────────────────────────────────────────────

def get_default_api_key() -> str:
    """返回默认 API 密钥。"""
    return os.environ.get("HOTPOT_API_KEY", "edge_yuhuan_dev_key")


# ── 门店上下文（用于NL/Agent）──────────────────────────────────────────────────

_STORE_CONTEXT: dict[str, dict[str, str]] = {
    "store_yuhuan": {
        "display": "玉环店",
        "short": "yuhuan",
    },
    "store_jiaojiang": {
        "display": "椒江店",
        "short": "jiaojiang",
    },
}


def get_store_display(store_id: str) -> str:
    """返回门店中文显示名。"""
    return _STORE_CONTEXT.get(store_id, {}).get("display", store_id)


def get_store_short(store_id: str) -> str:
    """返回门店短名。"""
    return _STORE_CONTEXT.get(store_id, {}).get("short", store_id)
