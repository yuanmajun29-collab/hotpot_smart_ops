"""Shared singleton container + FastAPI dependency providers.

Routers depend on get_hub/get_db/get_alert_gateway (late binding) instead of
importing module-level globals, so tests can swap instances via init().
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from cloud.alert_gateway.gateway import AlertGateway
    from cloud.event_hub.hub_core import MultiTenantHub

hub: Optional["MultiTenantHub"] = None
db: Any = None
alert_gateway: Optional["AlertGateway"] = None

# Org registry is a process-wide singleton; default to the canonical instance so
# the app works without explicit injection. Tests override `runtime.org_registry`.
from cloud.event_hub.org_registry import org_registry as org_registry  # noqa: E402


def init(hub_: "MultiTenantHub", db_: Any, alert_gateway_: "AlertGateway") -> None:
    global hub, db, alert_gateway
    hub = hub_
    db = db_
    alert_gateway = alert_gateway_


def get_hub() -> "MultiTenantHub":
    if hub is None:
        raise RuntimeError("runtime.hub not initialized")
    return hub


def get_db() -> Any:
    if db is None:
        raise RuntimeError("runtime.db not initialized")
    return db


def get_alert_gateway() -> "AlertGateway":
    if alert_gateway is None:
        raise RuntimeError("runtime.alert_gateway not initialized")
    return alert_gateway
