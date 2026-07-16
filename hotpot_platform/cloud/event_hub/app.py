"""FastAPI Event Hub (DEV-101 + DEV-102)."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from hotpot_platform.cloud.alert_gateway.gateway import AlertGateway
from hotpot_platform.cloud.event_hub.auth import DEFAULT_JWT_SECRET
from hotpot_platform.cloud.event_hub.db import create_hub_database
from hotpot_platform.cloud.event_hub.daily_scheduler import (
    DailyReportScheduler,
    default_loss_profiles,
)
from hotpot_platform.cloud.event_hub.hub_core import MultiTenantHub, seed_from_directory

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = PROJECT_ROOT / "demo" / "data" / "hub.db"
DEFAULT_ALERT_DB = PROJECT_ROOT / "demo" / "data" / "hub_alerts.db"

from hotpot_platform.cloud.event_hub import runtime

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
_STRICT_DEPLOY_PROFILES = {"staging", "pilot", "uat", "production", "prod"}


def __getattr__(name: str):
    """Delegate reads of hub/db/alert_gateway to runtime (test compat)."""
    if name in ("hub", "db", "alert_gateway"):
        return getattr(runtime, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def deployment_profile() -> str:
    return os.environ.get("HOTPOT_ENV", os.environ.get("HOTPOT_DEPLOYMENT_PROFILE", "dev")).lower()


def cors_origins() -> list[str]:
    raw = os.environ.get("HOTPOT_CORS_ORIGINS", "").strip()
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    if deployment_profile() in _STRICT_DEPLOY_PROFILES:
        return []
    return ["*"]


def validate_deployment_profile() -> None:
    profile = deployment_profile()
    if profile not in _STRICT_DEPLOY_PROFILES:
        return

    origins = cors_origins()
    errors = []
    if os.environ.get("HOTPOT_AUTH_MODE") != "strict":
        errors.append("HOTPOT_AUTH_MODE must be strict")
    jwt_secret = os.environ.get("HOTPOT_JWT_SECRET", DEFAULT_JWT_SECRET)
    if jwt_secret == DEFAULT_JWT_SECRET or "CHANGE_ME" in jwt_secret or len(jwt_secret) < 32:
        errors.append("HOTPOT_JWT_SECRET must be a real secret (32+ chars, not demo/placeholder)")
    if not os.environ.get("HOTPOT_DATABASE_URL"):
        errors.append("HOTPOT_DATABASE_URL must be set for PostgreSQL")
    if not origins or "*" in origins:
        errors.append("HOTPOT_CORS_ORIGINS must be an explicit comma-separated allowlist")
    if not os.environ.get("HOTPOT_EDGE_API_KEYS"):
        errors.append("HOTPOT_EDGE_API_KEYS must replace demo edge keys")
    if errors:
        raise RuntimeError(f"Unsafe {profile} deployment profile: " + "; ".join(errors))


def startup() -> None:
    validate_deployment_profile()
    runtime.org_registry.apply_to_hub(runtime.hub)
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
        from hotpot_platform.cloud.event_hub.tasks import get_dispatch
        dispatch = get_dispatch()

        # 三时段损耗调度：15:00 备货建议 / 22:00 损耗复盘 / 周一 09:00 趋势周报
        global _daily_scheduler
        _daily_scheduler = DailyReportScheduler(profiles=default_loss_profiles(), dispatch=dispatch)
        _daily_scheduler.start()


def shutdown() -> None:
    global _daily_scheduler
    if _daily_scheduler is not None:
        _daily_scheduler.stop()
        _daily_scheduler = None


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    startup()
    try:
        yield
    finally:
        shutdown()


app = FastAPI(title="Hotpot Event Hub", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 静态文件服务（图片等） ──
_STATIC_DIR = Path(__file__).parent / "static"
_STATIC_DIR.mkdir(parents=True, exist_ok=True)
(_STATIC_DIR / "images").mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

_LEGACY_PATHS = {
    "/summary", "/events", "/tables", "/sop", "/pos", "/erp", "/cost", "/iot",
    "/stores", "/benchmark", "/sop/ask",
    "/alerts/routes", "/alerts/push-log", "/alerts/acks", "/alerts/escalations",
    "/alerts/test-push", "/alerts/ack",
}


@app.middleware("http")
async def _mark_deprecated(request, call_next):
    resp = await call_next(request)
    if request.url.path in _LEGACY_PATHS:
        resp.headers["Deprecation"] = "true"
    return resp



# ── 统一错误处理 ──
from hotpot_platform.cloud.event_hub.common.errors import register_error_handlers
register_error_handlers(app)

# ── 路由器自动发现（新增路由 = 在 routers/ 丢一个 .py 文件，导出 router 实例）──
from hotpot_platform.cloud.event_hub.routers import auto_include_routers
auto_include_routers(app)
