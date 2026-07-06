"""In-memory org registry with JSON persistence (Phase 2 stub · DEV-501)."""

from __future__ import annotations

import json
import os
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = PROJECT_ROOT / "demo" / "data" / "stores.json"
REGISTRY_PATH = Path(os.environ.get("HOTPOT_STORES_REGISTRY", str(DEFAULT_REGISTRY_PATH)))


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class OrgRegistry:
    """Mutable org tree backed by stores.json (stub persistence until DB)."""

    def __init__(self, path: Path = REGISTRY_PATH) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = {}
        self._audit: List[Dict[str, Any]] = []
        self.reload()

    def reload(self) -> None:
        with self._lock:
            if self._path.exists():
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            else:
                self._data = {
                    "brand": "冯校长火锅",
                    "parent_regions": [],
                    "regions": [],
                    "pilot_stores": [],
                }

    def save(self) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    def _log_audit(self, action: str, entity: str, entity_id: str, actor: str, detail: Any = None) -> None:
        self._audit.append(
            {
                "id": str(uuid.uuid4())[:8],
                "action": action,
                "entity": entity,
                "entity_id": entity_id,
                "actor": actor,
                "detail": detail,
                "created_at": _utc_now(),
            }
        )
        if len(self._audit) > 500:
            self._audit = self._audit[-500:]

    def get_org_tree(self) -> Dict[str, Any]:
        with self._lock:
            return deepcopy(self._data)

    def list_zones(self) -> List[Dict[str, Any]]:
        with self._lock:
            return deepcopy(self._data.get("parent_regions", []))

    def list_regions(self, zone_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            regions = deepcopy(self._data.get("regions", []))
            if zone_id:
                regions = [r for r in regions if r.get("parent_zone_id") == zone_id]
            return regions

    def list_stores(self) -> List[Dict[str, Any]]:
        with self._lock:
            return deepcopy(self._data.get("pilot_stores", []))

    def get_store(self, store_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for s in self._data.get("pilot_stores", []):
                if s.get("store_id") == store_id:
                    return deepcopy(s)
        return None

    def create_store(
        self,
        store_name: str,
        region_id: str,
        city: str = "",
        store_type: str = "direct",
        status: str = "preparing",
        actor: str = "admin",
    ) -> Dict[str, Any]:
        with self._lock:
            region = next(
                (r for r in self._data.get("regions", []) if r.get("region_id") == region_id),
                None,
            )
            if not region:
                raise ValueError(f"region not found: {region_id}")

            existing_ids = {s.get("store_id") for s in self._data.get("pilot_stores", [])}
            slug = region_id.replace("region_", "")[:6]
            n = 1
            while True:
                store_id = f"store_{slug}_{n:02d}"
                if store_id not in existing_ids:
                    break
                n += 1

            item = {
                "store_id": store_id,
                "store_name": store_name,
                "city": city or region.get("region_name", ""),
                "type": store_type,
                "status": status,
                "region_id": region_id,
                "note": f"Admin 创建 · {_utc_now()[:10]}",
            }
            self._data.setdefault("pilot_stores", []).append(item)
            region.setdefault("store_ids", []).append(store_id)
            self._log_audit("create", "store", store_id, actor, item)
            self.save()
            return deepcopy(item)

    def update_store(
        self,
        store_id: str,
        actor: str = "admin",
        **fields: Any,
    ) -> Dict[str, Any]:
        allowed = {"store_name", "city", "type", "status", "note", "region_id"}
        with self._lock:
            stores = self._data.get("pilot_stores", [])
            item = next((s for s in stores if s.get("store_id") == store_id), None)
            if not item:
                raise ValueError(f"store not found: {store_id}")

            old_region = item.get("region_id")
            for k, v in fields.items():
                if k in allowed and v is not None:
                    item[k] = v

            new_region = fields.get("region_id")
            if new_region and new_region != old_region:
                for r in self._data.get("regions", []):
                    if old_region and r.get("region_id") == old_region:
                        r["store_ids"] = [x for x in r.get("store_ids", []) if x != store_id]
                    if r.get("region_id") == new_region:
                        if store_id not in r.get("store_ids", []):
                            r.setdefault("store_ids", []).append(store_id)

            self._log_audit("update", "store", store_id, actor, fields)
            self.save()
            return deepcopy(item)

    def list_audit(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return deepcopy(self._audit[-limit:][::-1])

    def apply_to_hub(self, hub: Any) -> None:
        """Sync hub in-memory registry from org file."""
        with self._lock:
            hub._zones = list(self._data.get("parent_regions", []))
            hub._regions = list(self._data.get("regions", []))
            hub._registry = {
                s["store_id"]: dict(s)
                for s in self._data.get("pilot_stores", [])
                if s.get("store_id")
            }


# Singleton for app lifecycle
org_registry = OrgRegistry()
