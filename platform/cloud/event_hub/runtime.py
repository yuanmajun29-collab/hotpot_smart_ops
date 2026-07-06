"""Shared singleton container with late binding.

Routers reference `runtime.hub` / `runtime.db` / `runtime.alert_gateway` /
`runtime.org_registry` directly at call time, so tests can swap instances via
`init()` (and by assigning `runtime.org_registry`) without re-importing routers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from platform.cloud.alert_gateway.gateway import AlertGateway
    from platform.cloud.event_hub.hub_core import MultiTenantHub

hub: Optional["MultiTenantHub"] = None
db: Any = None
alert_gateway: Optional["AlertGateway"] = None

# Org registry is a process-wide singleton; default to the canonical instance so
# the app works without explicit injection. Tests override `runtime.org_registry`.
from platform.cloud.event_hub import org_registry as _org_registry_module  # noqa: E402

org_registry = _org_registry_module.org_registry


def init(hub_: "MultiTenantHub", db_: Any, alert_gateway_: "AlertGateway") -> None:
    global hub, db, alert_gateway
    hub = hub_
    db = db_
    alert_gateway = alert_gateway_
