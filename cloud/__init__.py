"""Backward-compatible alias for hotpot_platform.cloud.

Older launch commands and tests still refer to cloud.event_hub.*. The canonical
package is hotpot_platform.cloud, but these aliases keep both names bound to the
same module objects so monkeypatches and imports land on the active code.
"""

from __future__ import annotations

import importlib
import sys

_cloud = importlib.import_module("hotpot_platform.cloud")
_event_hub = importlib.import_module("hotpot_platform.cloud.event_hub")
_routers = importlib.import_module("hotpot_platform.cloud.event_hub.routers")
_cost = importlib.import_module("hotpot_platform.cloud.event_hub.routers.cost")

sys.modules.setdefault("cloud", _cloud)
sys.modules.setdefault("cloud.event_hub", _event_hub)
sys.modules.setdefault("cloud.event_hub.routers", _routers)
sys.modules.setdefault("cloud.event_hub.routers.cost", _cost)

event_hub = _event_hub
setattr(_event_hub, "routers", _routers)
setattr(_routers, "cost", _cost)
