"""FastAPI Event Hub (DEV-101 + DEV-102)."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_START_TIME = time.time()

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from cloud.event_hub.auth import (
    AUTH_MODE,
    AuthContext,
    TokenRequest,
    can_admin,
    data_scope_for_role,
    enforce_action,
    enforce_admin,
    enforce_store_read,
    enforce_store_write,
    get_auth_context,
    login_user,
)
from cloud.alert_gateway.gateway import AlertGateway
from cloud.event_hub.device_stub import (
    get_pipeline_status,
    run_subprocess_pipeline,
    tick_all_stores_inprocess,
    tick_store_inprocess,
)
from cloud.event_hub.org_registry import org_registry
from cloud.event_hub.db import create_hub_database
from cloud.event_hub.daily_report_store import daily_report_store
from cloud.event_hub.daily_scheduler import DailyReportScheduler, generate_daily_report_for_store
from cloud.event_hub.iot_readings_store import iot_readings_store
from cloud.event_hub.receiving_store import new_batch_id, receiving_store, variance_pct
from cloud.event_hub.sop_assign_store import sop_assign_store
from cloud.event_hub.hub_core import DEFAULT_STORE_ID, MultiTenantHub, seed_from_directory

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = PROJECT_ROOT / "demo" / "data" / "hub.db"
DEFAULT_ALERT_DB = PROJECT_ROOT / "demo" / "data" / "hub_alerts.db"

from cloud.event_hub import runtime
from cloud.event_hub.routers._deps import (
    resolve_store_id as _resolve_store_id,
    _enforce_report_generate,
    _append_cost_item,
    SopAskBody, AlertAckBody, SignatureInput, ReceivingSubmitBody,
    SopAssignBody, SopAssignStatusBody, IotReadingInput, IotReadingsBatchBody,
    DailyReportGenerateBody, AdminStoreCreate, AdminStoreUpdate, PipelineTickBody,
)

_db_path = Path(os.environ.get("HOTPOT_DB", str(DEFAULT_DB)))
_database_url = os.environ.get("HOTPOT_DATABASE_URL", "")
_alert_db_path = Path(os.environ.get("HOTPOT_ALERT_DB", str(_db_path if not _database_url else DEFAULT_ALERT_DB)))

_db = create_hub_database(_db_path, _database_url)
runtime.init(
    MultiTenantHub(on_persist=_db.on_persist),
    _db,
    AlertGateway(_alert_db_path),
)
_daily_scheduler: Optional[DailyReportScheduler] = None


def __getattr__(name: str):
    """Delegate reads of hub/db/alert_gateway to runtime (test compat)."""
    if name in ("hub", "db", "alert_gateway"):
        return getattr(runtime, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

app = FastAPI(title="Hotpot Event Hub", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    org_registry.apply_to_hub(runtime.hub)
    seed_dir = os.environ.get("HOTPOT_SEED_DIR", "")
    if not runtime.db.is_empty():
        runtime.db.hydrate_hub(runtime.hub)
        print(f"[EventHub] Hydrated from {runtime.db.db_path}")
    elif seed_dir:
        n = seed_from_directory(runtime.hub, Path(seed_dir))
        print(f"[EventHub] Seeded {n} store(s) from {seed_dir}")
    else:
        print("[EventHub] Started empty (no DB data, no seed dir)")

    if os.environ.get("HOTPOT_DAILY_REPORT_SCHEDULER", "1") == "1":

        def _gen(sid: str, push: bool) -> Dict[str, Any]:
            return generate_daily_report_for_store(runtime.hub, runtime.db, runtime.alert_gateway, sid, push=push)

        global _daily_scheduler
        _daily_scheduler = DailyReportScheduler(_gen)
        _daily_scheduler.start()




from cloud.event_hub.routers import system as _system_router
from cloud.event_hub.routers import auth_routes as _auth_routes_router
from cloud.event_hub.routers import ingest as _ingest_router
from cloud.event_hub.routers import receiving as _receiving_router
from cloud.event_hub.routers import sop as _sop_router
from cloud.event_hub.routers import iot as _iot_router
from cloud.event_hub.routers import reports as _reports_router
from cloud.event_hub.routers import alerts as _alerts_router
from cloud.event_hub.routers import org as _org_router
from cloud.event_hub.routers import admin as _admin_router

app.include_router(_system_router.router)
app.include_router(_auth_routes_router.router)
app.include_router(_ingest_router.router)
app.include_router(_receiving_router.router)
app.include_router(_sop_router.router)
app.include_router(_iot_router.router)
app.include_router(_reports_router.router)
app.include_router(_alerts_router.router)
app.include_router(_org_router.router)
app.include_router(_admin_router.router)
