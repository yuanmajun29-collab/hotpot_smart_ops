# Event Hub Router-Split Refactor 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `cloud/event_hub/app.py`（986 行 / 54 路由）按 8 业务域拆成 router 子包，统一 /v1 前缀（旧路径加 deprecation），抽出领域计算层，且端点行为零变化。

**Architecture:** 引入 `runtime.py` 单例容器 + FastAPI 依赖注入（`Depends(get_hub/get_db/get_alert_gateway)`）替代模块级全局；路由迁入 `routers/*.py`，每域一个 `APIRouter`；纯业务函数迁入 `domain/`。`app.py` 收敛为组装根。

**Tech Stack:** FastAPI · pydantic · pytest（59 个既有测试为回归护栏）· SQLite/PostgreSQL

**关键约束：** 这是**行为保持型重构**。既有 59 个测试是验收护栏——每个 Task 完成后必须 `pytest` 全绿。绝不改端点路径/响应结构（旧路径保留 + 新增 /v1 别名）。

---

## 基线确认（执行前先跑一次）

```bash
python3 -m pip install -q fastapi 'uvicorn[standard]' pyjwt pydantic pytest httpx
python3 -m pytest tests/ -q
```
预期：`59 passed`。若非 59 passed，停止，先排查环境。

---

## 文件结构

| 文件 | 职责 | 动作 |
|------|------|------|
| `cloud/event_hub/runtime.py` | hub/db/alert_gateway 单例 + 依赖提供者 + `init()` | 新建 |
| `cloud/event_hub/routers/__init__.py` | 空包标记 | 新建 |
| `cloud/event_hub/routers/_deps.py` | 共享 helper（`resolve_store_id` 等）+ pydantic body 模型 | 新建 |
| `cloud/event_hub/routers/system.py` | `/health` `/metrics` `/seed` | 新建 |
| `cloud/event_hub/routers/auth_routes.py` | `/auth/token` `/v1/auth/me` | 新建 |
| `cloud/event_hub/routers/ingest.py` | 旧 GET/POST `/events /tables /pos /sop /cost /iot /erp` + `/summary` `/stores` | 新建 |
| `cloud/event_hub/routers/receiving.py` | `/v1/receiving/*` `/v1/audit/signatures` | 新建 |
| `cloud/event_hub/routers/sop.py` | `/v1/sop/*` `/sop/ask` | 新建 |
| `cloud/event_hub/routers/iot.py` | `/v1/iot/*` | 新建 |
| `cloud/event_hub/routers/reports.py` | `/v1/reports/daily/*` | 新建 |
| `cloud/event_hub/routers/alerts.py` | `/alerts/*` `/v1/audit/acks` | 新建 |
| `cloud/event_hub/routers/org.py` | `/benchmark` `/v1/region/overview` `/v1/national/overview` | 新建 |
| `cloud/event_hub/routers/admin.py` | `/v1/admin/*` | 新建 |
| `cloud/event_hub/domain/__init__.py` | 空包标记 | 新建 |
| `cloud/event_hub/domain/health.py` | `compute_store_health` `_rollup_from_rows` `_region_worst_health` | 新建 |
| `cloud/event_hub/domain/turnover.py` | `turnover_suggestions` | 新建 |
| `cloud/event_hub/hub_core.py` | 瘦身：状态管理；re-export domain 函数 | 改 |
| `cloud/event_hub/app.py` | 组装根 | 改（大幅缩减） |
| `tests/test_*.py`（11 个 fixture） | 注入点 `app.* =` → `runtime.*` | 改 |
| `dashboard/assets/core.js` | 旧路径 fetch → /v1 | 改 |

---

## Phase 0 — Runtime 容器（不动路由，先验证机制）

### Task 1: 创建 runtime.py

**Files:**
- Create: `cloud/event_hub/runtime.py`

- [ ] **Step 1: 写 runtime.py**

```python
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
```

- [ ] **Step 2: 验证可导入**

Run: `python3 -c "from cloud.event_hub import runtime; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add cloud/event_hub/runtime.py
git commit -m "feat(hub): add runtime singleton container + DI providers"
```

### Task 2: app.py 改用 runtime.init（路由仍读全局）

此步只改装配：让 `app.py` 把单例注入 runtime，并让 `app.hub/db/alert_gateway` 的**读**委托给 runtime（保留测试读取点）。路由本体暂不动。

**Files:**
- Modify: `cloud/event_hub/app.py:50-55`（全局赋值段）、startup 段

- [ ] **Step 1: 替换全局赋值段**

把现有：
```python
_db_path = Path(os.environ.get("HOTPOT_DB", str(DEFAULT_DB)))
_database_url = os.environ.get("HOTPOT_DATABASE_URL", "")
db = create_hub_database(_db_path, _database_url)
_alert_db_path = Path(os.environ.get("HOTPOT_ALERT_DB", str(_db_path if not _database_url else DEFAULT_ALERT_DB)))
hub = MultiTenantHub(on_persist=db.on_persist)
alert_gateway = AlertGateway(_alert_db_path)
_daily_scheduler: Optional[DailyReportScheduler] = None
```
改为：
```python
from cloud.event_hub import runtime

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
```

> 已核对 `hub_core.py:287`：`MultiTenantHub.__init__(self, on_persist=None)` 把 `on_persist` 存为 `self._on_persist` 实例属性，故先建 db 再 `MultiTenantHub(on_persist=_db.on_persist)` 即保持原行为，无需 setter。

- [ ] **Step 2: 全局引用替换为 runtime getter（route 内）**

app.py 内所有路由函数体里直接用的 `hub.` / `db` / `alert_gateway.`：暂时**不改**（靠 `__getattr__` 委托读取仍可工作，因为它们引用的是模块全局名，而模块已无这些真实属性 → 触发 `__getattr__`）。验证此假设见 Step 3。

- [ ] **Step 3: 跑全量测试**

Run: `python3 -m pytest tests/ -q`
Expected: `59 passed`
若失败且报 `__getattr__` 未命中（因函数内 `hub` 被解析为全局但模块有同名遗留属性）：确认 Step 1 已删除 `hub =`/`db =`/`alert_gateway =` 赋值行，使其成为缺失属性。

- [ ] **Step 4: 更新 startup 段使用 runtime**

把 `startup()` 内 `org_registry.apply_to_hub(hub)` 等对 `hub`/`db`/`alert_gateway` 的引用确认仍走 `__getattr__`（无需改）。`_gen` 闭包里的 `hub, db, alert_gateway` 同理。Run 测试再次确认 `59 passed`。

- [ ] **Step 5: Commit**

```bash
git add cloud/event_hub/app.py
git commit -m "refactor(hub): route singletons through runtime.init (no behavior change)"
```

### Task 3: 迁移测试 fixture 注入点 → runtime

**Files:**
- Modify: `tests/test_hub_smoke.py` `test_receiving_api.py` `test_erp_bridge.py` `test_pos_bridge.py` `test_iot_stub.py` `test_admin_api.py` `test_cockpit_api.py` `test_sop_assign_api.py` `test_daily_report_api.py` `test_region_overview.py` `test_wechat_webhook_e2e.py`

- [ ] **Step 1: 标准三行替换**

每个 fixture 中的：
```python
hub_app_module.db = create_hub_database(db_path)
hub_app_module.hub = hub_app_module.MultiTenantHub(on_persist=hub_app_module.db.on_persist)
hub_app_module.alert_gateway = hub_app_module.AlertGateway(db_path)
```
替换为：
```python
from cloud.event_hub import runtime
_db = create_hub_database(db_path)
runtime.init(
    hub_app_module.MultiTenantHub(on_persist=_db.on_persist),
    _db,
    hub_app_module.AlertGateway(db_path),
)
```
读取点（如 `seed_from_directory(hub_app_module.hub, ...)`、`reg.apply_to_hub(hub_app_module.hub)`）**保持不变**——靠 `app.__getattr__` 委托到 runtime。

- [ ] **Step 2: 处理中途重设 alert_gateway**

`test_daily_report_api.py:105`、`test_wechat_webhook_e2e.py:75/119/145` 的：
```python
hub_app_module.alert_gateway = hub_app_module.AlertGateway(...)
```
替换为：
```python
runtime.alert_gateway = hub_app_module.AlertGateway(...)
```

- [ ] **Step 3: 跑全量测试**

Run: `python3 -m pytest tests/ -q`
Expected: `59 passed`

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test(hub): inject singletons via runtime.init instead of app globals"
```

---

## Phase 1 — 领域层抽取（P3）

### Task 4: 抽 domain/health.py + turnover.py

**Files:**
- Create: `cloud/event_hub/domain/__init__.py`（空）
- Create: `cloud/event_hub/domain/health.py`
- Create: `cloud/event_hub/domain/turnover.py`
- Modify: `cloud/event_hub/hub_core.py`

- [ ] **Step 1: 创建 domain 包**

Run: `mkdir -p cloud/event_hub/domain && : > cloud/event_hub/domain/__init__.py`

- [ ] **Step 2: 把纯函数剪切到 domain/health.py**

将 `hub_core.py` 中的 `compute_store_health`、`_rollup_from_rows`、`_region_worst_health` 三个函数体（连同所需 import：`from typing import Any, Dict, List`）**移动**到 `cloud/event_hub/domain/health.py`。函数体逐字保留，不改逻辑。

- [ ] **Step 3: 把 turnover_suggestions 剪切到 domain/turnover.py**

将 `turnover_suggestions` 移动到 `cloud/event_hub/domain/turnover.py`（连同 `from typing import Any, Dict, List`）。

- [ ] **Step 4: hub_core re-export 以零改调用方**

在 `hub_core.py` 顶部（import 段之后）加：
```python
from cloud.event_hub.domain.health import (
    compute_store_health,
    _rollup_from_rows,
    _region_worst_health,
)
from cloud.event_hub.domain.turnover import turnover_suggestions
```
确保 `hub_core` 内部其它代码（如 `MultiTenantHub.get_region_overview`）对这些函数的调用仍解析到 re-export 名。`tests/test_region_overview.py` 的 `from cloud.event_hub.hub_core import compute_store_health` 因此无需改。

- [ ] **Step 5: 跑全量测试**

Run: `python3 -m pytest tests/ -q`
Expected: `59 passed`

- [ ] **Step 6: Commit**

```bash
git add cloud/event_hub/domain/ cloud/event_hub/hub_core.py
git commit -m "refactor(hub): extract health/turnover domain logic from hub_core"
```

---

## Phase 2 — 共享 helper 提取

### Task 5: routers/_deps.py + body 模型

把 app.py 的共享 helper 与 pydantic body 模型迁出，供各 router 复用。

**Files:**
- Create: `cloud/event_hub/routers/__init__.py`（空）
- Create: `cloud/event_hub/routers/_deps.py`
- Modify: `cloud/event_hub/app.py`

- [ ] **Step 1: 创建 routers 包**

Run: `mkdir -p cloud/event_hub/routers && : > cloud/event_hub/routers/__init__.py`

- [ ] **Step 2: 迁 helper 与 body 模型到 _deps.py**

将 app.py 中的 `_resolve_store_id`、`_enforce_report_generate`、`_append_cost_item`，以及所有 pydantic body 模型（`ReceivingSubmitBody`、`SopAssignBody`、`SopAssignStatusBody`、`IotReadingInput`、`IotReadingsBatchBody`、`DailyReportGenerateBody`、`SopAskBody`、`AlertAckBody`、`AdminStoreCreate`、`AdminStoreUpdate`、`PipelineTickBody` 等——以 app.py 实际定义为准）剪切到 `routers/_deps.py`。

`_resolve_store_id` 改名导出为 `resolve_store_id`（去掉前导下划线，因跨模块复用），签名不变：
```python
def resolve_store_id(store_id, body, header_store, auth) -> str:
    sid = header_store or store_id
    if not sid and isinstance(body, dict):
        sid = body.get("store_id")
    if not sid and isinstance(body, list) and body and isinstance(body[0], dict):
        sid = body[0].get("store_id")
    sid = sid or DEFAULT_STORE_ID
    enforce_store_read(auth, sid)
    return sid
```
`_deps.py` 需 import：`from cloud.event_hub.auth import enforce_store_read, enforce_action, AuthContext`、`from cloud.event_hub.hub_core import DEFAULT_STORE_ID`。

- [ ] **Step 3: app.py 改为从 _deps 导入**

app.py 顶部加 `from cloud.event_hub.routers._deps import (resolve_store_id as _resolve_store_id, ...)` 并删除原定义。其余路由暂不动。

- [ ] **Step 4: 跑全量测试**

Run: `python3 -m pytest tests/ -q`
Expected: `59 passed`

- [ ] **Step 5: Commit**

```bash
git add cloud/event_hub/routers/ cloud/event_hub/app.py
git commit -m "refactor(hub): extract shared deps and body models to routers/_deps"
```

---

## Phase 3 — 按域迁移路由（每域一 Task，迁完即测）

**统一迁移模式**（每个 router 文件套用）：

```python
"""<域名> routes."""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from cloud.event_hub.auth import (AuthContext, get_auth_context, enforce_store_write,
                                  enforce_action, ...)
from cloud.event_hub.runtime import get_hub, get_db, get_alert_gateway
from cloud.event_hub.routers._deps import resolve_store_id, <body 模型...>
from cloud.event_hub.hub_core import DEFAULT_STORE_ID

router = APIRouter()

@router.post("/v1/receiving/submit")
def receiving_submit(body: ReceivingSubmitBody,
                     auth: AuthContext = Depends(get_auth_context),
                     hub=Depends(get_hub), db=Depends(get_db)) -> Dict[str, Any]:
    # 函数体逐字搬运；把裸 `hub`/`db`/`alert_gateway` 改为注入参数
    ...
```

转换规则（机械）：
1. `@app.X(...)` → `@router.X(...)`
2. 函数签名追加需要的 `hub=Depends(get_hub)` / `db=Depends(get_db)` / `alert_gateway=Depends(get_alert_gateway)`（仅加该函数体实际用到的）
3. 函数体内 `hub.`/`db`/`alert_gateway.` 引用保持不变（现在指向注入参数）
4. 调用 `generate_daily_report_for_store(hub, db, alert_gateway, ...)` 等显式传参的，改用注入参数
5. app.py 中删除已迁出的路由定义，并在装配处 `app.include_router(<module>.router)`

每个 Task 完成后均 Run `python3 -m pytest tests/ -q` 期望 `59 passed`，然后 commit。

### Task 6: system 域 → routers/system.py
路由：`/health` `/metrics` `/seed`。`/seed` 用 `hub`；`/metrics` 用 `hub`。`/health` 读 `runtime`/env（保持原逻辑，可不注入）。
- [ ] 建 `system.py`，按模式迁移；app.py 删除三路由 + `app.include_router(system.router)`
- [ ] Run `python3 -m pytest tests/ -q` → `59 passed`
- [ ] `git commit -m "refactor(hub): split system routes into routers/system.py"`

### Task 7: auth 域 → routers/auth_routes.py
路由：`/auth/token`（用 `login_user`）`/v1/auth/me`（用 auth + `can_admin`/`data_scope_for_role`）。无需 hub/db。
- [ ] 建 `auth_routes.py`，迁移；app.py include
- [ ] Run `pytest` → `59 passed`
- [ ] `git commit -m "refactor(hub): split auth routes into routers/auth_routes.py"`

### Task 8: ingest 域 → routers/ingest.py
路由：GET `/summary` `/events` `/tables` `/sop` `/pos` `/erp` `/cost` `/iot` `/stores`；POST `/events` `/tables` `/pos` `/sop` `/cost` `/iot` `/erp`。POST `/events` 用 `hub` + `alert_gateway`。其余多数用 `hub`。
- [ ] 建 `ingest.py`，迁移全部 ingest 路由；app.py include
- [ ] Run `pytest` → `59 passed`（覆盖 test_pos_bridge / test_erp_bridge / test_iot_stub / test_hub_smoke）
- [ ] `git commit -m "refactor(hub): split ingest routes into routers/ingest.py"`

### Task 9: receiving 域 → routers/receiving.py
路由：`/v1/receiving/submit` `/v1/receiving/batches` `/v1/audit/signatures`。用 `hub` + `db` + `_append_cost_item`。
- [ ] 迁移；app.py include
- [ ] Run `pytest tests/test_receiving_api.py -q` 然后全量 `pytest` → `59 passed`
- [ ] `git commit -m "refactor(hub): split receiving routes into routers/receiving.py"`

### Task 10: sop 域 → routers/sop.py
路由：`/v1/sop/assign` `/v1/sop/assignments` `/v1/sop/assignments/{id}/status` `/sop/ask`。用 `hub` + `db`；`/sop/ask` 用 `create_sop_agent`（保留 import）。
- [ ] 迁移；app.py include
- [ ] Run `pytest tests/test_sop_assign_api.py tests/test_sop_rag.py -q` 然后全量 → `59 passed`
- [ ] `git commit -m "refactor(hub): split sop routes into routers/sop.py"`

### Task 11: iot 域 → routers/iot.py
路由：`/v1/iot/readings/batch` `/v1/iot/readings`。用 `db`（`iot_readings_store(db)`）。
- [ ] 迁移；app.py include
- [ ] Run `pytest` → `59 passed`
- [ ] `git commit -m "refactor(hub): split iot routes into routers/iot.py"`

### Task 12: reports 域 → routers/reports.py
路由：`/v1/reports/daily/generate` `/v1/reports/daily`。`generate` 调 `generate_daily_report_for_store(hub, db, alert_gateway, ...)`，需注入三者。
- [ ] 迁移；app.py include
- [ ] Run `pytest tests/test_daily_report_api.py -q` 然后全量 → `59 passed`
- [ ] `git commit -m "refactor(hub): split reports routes into routers/reports.py"`

### Task 13: alerts 域 → routers/alerts.py
路由：`/alerts/routes` `/alerts/test-push` `/alerts/push-log` `/alerts/acks` `/alerts/ack` `/alerts/escalations` `/v1/audit/acks`。用 `alert_gateway` + `hub` + `db`（`/v1/audit/acks` 用 `receiving_store`/`sop_assign_store`）。
- [ ] 迁移；app.py include
- [ ] Run `pytest tests/test_wechat_webhook_e2e.py -q` 然后全量 → `59 passed`
- [ ] `git commit -m "refactor(hub): split alerts routes into routers/alerts.py"`

### Task 14: org 域 → routers/org.py
路由：`/benchmark` `/v1/region/overview` `/v1/national/overview`。用 `hub`。
- [ ] 迁移；app.py include
- [ ] Run `pytest tests/test_region_overview.py tests/test_cockpit_api.py -q` 然后全量 → `59 passed`
- [ ] `git commit -m "refactor(hub): split org/region routes into routers/org.py"`

### Task 15: admin 域 → routers/admin.py
路由：`/v1/admin/org-tree` `/v1/admin/stores`(GET/POST) `/v1/admin/stores/{id}`(PUT) `/v1/admin/users` `/v1/admin/audit-logs` `/v1/admin/pipeline/status` `/v1/admin/pipeline/tick`。用 `hub` + `org_registry` + `get_pipeline_status` 等。
- [ ] 迁移；app.py include
- [ ] Run `pytest tests/test_admin_api.py -q` 然后全量 → `59 passed`
- [ ] `git commit -m "refactor(hub): split admin routes into routers/admin.py"`

### Task 16: app.py 收敛为组装根

**Files:**
- Modify: `cloud/event_hub/app.py`

- [ ] **Step 1: 确认 app.py 仅剩**

import、CORS、`runtime.init`、`startup()`/`shutdown()`、依次 `app.include_router(...)`、`__getattr__` 委托。无任何 `@app.get/post/put`。

- [ ] **Step 2: 跑全量 + 行检查**

Run: `python3 -m pytest tests/ -q && wc -l cloud/event_hub/app.py`
Expected: `59 passed`，行数 ≤ ~120。

- [ ] **Step 3: Commit**

```bash
git add cloud/event_hub/app.py
git commit -m "refactor(hub): app.py reduced to composition root"
```

---

## Phase 4 — P2 旧路径 /v1 统一 + deprecation

### Task 17: 旧路径加 deprecation + 新增 /v1 别名

**Files:**
- Modify: `cloud/event_hub/routers/ingest.py` `org.py` `alerts.py` `sop.py` `system.py`

- [ ] **Step 1: 新增 /v1 别名（双注册）**

对每个无前缀旧路径，在同 router 内额外注册等价 `/v1/...` 路由，复用同一处理函数：
```python
# ingest.py 示例
def _summary_impl(request, store_id, auth, hub):
    sid = resolve_store_id(store_id, None, request.headers.get("x-store-id"), auth)
    return hub.get_store(sid).get_summary()

@router.get("/summary", deprecated=True)
def summary_legacy(request: Request, store_id: Optional[str] = Query(None),
                   auth: AuthContext = Depends(get_auth_context), hub=Depends(get_hub)):
    return _summary_impl(request, store_id, auth, hub)

@router.get("/v1/summary")
def summary_v1(request: Request, store_id: Optional[str] = Query(None),
               auth: AuthContext = Depends(get_auth_context), hub=Depends(get_hub)):
    return _summary_impl(request, store_id, auth, hub)
```
对以下旧路径建 /v1 别名并将旧路由标 `deprecated=True`：`/summary /events /tables /sop /pos /erp /cost /iot /stores`（ingest）、`/benchmark`（org）、`/alerts/*`（alerts）、`/sop/ask`（sop）。

- [ ] **Step 2: 加 Deprecation 响应头**

在 app.py 装配处加一个 middleware，对路径不以 `/v1` 开头的成功响应加头：
```python
@app.middleware("http")
async def _mark_deprecated(request, call_next):
    resp = await call_next(request)
    p = request.url.path
    if p != "/health" and not p.startswith("/v1") and not p.startswith("/auth"):
        resp.headers["Deprecation"] = "true"
    return resp
```

- [ ] **Step 3: 新增测试断言 /v1 别名 + deprecation 头**

Create: `tests/test_v1_aliases.py`
```python
import os, tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

@pytest.fixture()
def client():
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "t.db"
    os.environ["HOTPOT_DB"] = str(db_path)
    os.environ["HOTPOT_AUTH_MODE"] = "demo"
    os.environ.pop("HOTPOT_SEED_DIR", None)
    os.environ.pop("HOTPOT_DATABASE_URL", None)
    from cloud.event_hub import app as m
    from cloud.event_hub import runtime
    _db = m.create_hub_database(db_path)
    runtime.init(m.MultiTenantHub(on_persist=_db.on_persist), _db, m.AlertGateway(db_path))
    return TestClient(m.app)

def test_v1_summary_alias_matches_legacy(client):
    a = client.get("/summary?store_id=store_yuhuan")
    b = client.get("/v1/summary?store_id=store_yuhuan")
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()

def test_legacy_has_deprecation_header(client):
    r = client.get("/summary?store_id=store_yuhuan")
    assert r.headers.get("Deprecation") == "true"

def test_v1_has_no_deprecation_header(client):
    r = client.get("/v1/summary?store_id=store_yuhuan")
    assert "Deprecation" not in r.headers
```

- [ ] **Step 4: 跑测试**

Run: `python3 -m pytest tests/ -q`
Expected: `62 passed`（59 + 3 新）

- [ ] **Step 5: Commit**

```bash
git add cloud/event_hub/routers/ cloud/event_hub/app.py tests/test_v1_aliases.py
git commit -m "feat(hub): add /v1 aliases for legacy paths with deprecation marking (ADR-004)"
```

### Task 18: 前端 core.js 切换到 /v1

**Files:**
- Modify: `dashboard/assets/core.js`

- [ ] **Step 1: 改 fetch 路径**

将 `core.js` 中旧路径 fetch 改为 /v1：`/summary`→`/v1/summary`、`/events`→`/v1/events`、`/stores`→`/v1/stores`、`/erp`→`/v1/erp`、`/sop/ask`→`/v1/sop/ask`、`/benchmark`→`/v1/benchmark`、`/alerts/ack`→`/v1/alerts/ack`、`/alerts/push-log`→`/v1/alerts/push-log`、`/alerts/acks`→`/v1/alerts/acks`、`/alerts/escalations`→`/v1/alerts/escalations`、`/alerts/routes`→`/v1/alerts/routes`。`/health` `/metrics` `/auth/token` 保持（非 deprecated）。

- [ ] **Step 2: 手工冒烟**

Run:
```bash
HOTPOT_DB=$(mktemp -d)/smoke.db python3 -m uvicorn cloud.event_hub.app:app --port 8088 &
sleep 2
curl -s http://127.0.0.1:8088/v1/summary?store_id=store_yuhuan | head -c 120
curl -s -D- -o /dev/null http://127.0.0.1:8088/v1/summary?store_id=store_yuhuan | grep -i deprecation || echo "no-deprecation-on-v1 OK"
kill %1
```
Expected：/v1/summary 返回 JSON；无 Deprecation 头。

- [ ] **Step 3: Commit**

```bash
git add dashboard/assets/core.js
git commit -m "refactor(dashboard): point core.js fetch at /v1 endpoints"
```

---

## Phase 5 — 收尾验收

### Task 19: 最终验收 + DoD 勾选

- [ ] **Step 1: 全量测试**

Run: `python3 -m pytest tests/ -q`
Expected: `62 passed`

- [ ] **Step 2: 行数与结构核对**

Run: `wc -l cloud/event_hub/app.py cloud/event_hub/routers/*.py cloud/event_hub/domain/*.py`
Expected：app.py ≤ ~120 行；每个 router 聚焦单域。

- [ ] **Step 3: run_poc 冒烟**

Run: `bash demo/run_poc.sh`（或文档所述启动方式），打开 dashboard 各页确认数据正常。
Expected：无 404、各页加载正常。

- [ ] **Step 4: 更新 spec DoD 勾选 + 提交**

在 `docs/superpowers/specs/2026-06-17-event-hub-router-split-design.md` §6 勾选已完成项。
```bash
git add docs/superpowers/specs/2026-06-17-event-hub-router-split-design.md
git commit -m "docs: check off router-split DoD"
```

---

## Self-Review 备注

- **Spec 覆盖**：P1（Task 5-16）、P2（Task 17-18）、P3（Task 4）、runtime 机制（Task 1-3）、测试迁移（Task 3）、DoD（Task 19）均有对应 Task。
- **关键风险**：`app.__getattr__` 仅对缺失属性生效——Task 2 Step 1 已删除模块级 `hub=`/`db=`/`alert_gateway=` 赋值使其成为缺失属性，Task 2 Step 3 加了验证。`on_persist` 绑定已核实（hub_core.py:287，实例属性，无需 setter）。
- **护栏**：每 Task 后全量 `pytest`，期望基线 59 → 终态 62 passed。
