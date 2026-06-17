# Event Hub 按业务域拆 Router · 重构设计

| 项目 | 内容 |
|------|------|
| 版本 | V1.0 |
| 日期 | 2026-06-17 |
| 范围 | P1（GOD FILE 拆分）+ P2（/v1 统一）+ P3（领域层抽取） |
| 关联 | [ADR-004](../../architecture_decisions.md) · `cloud/event_hub/app.py` |

---

## 1. 背景与问题

`cloud/event_hub/app.py` 单文件 986 行、54 个路由，混合 8 个业务域（收货、SOP、IoT、告警、Admin、日报、区域/全国、原始 ingest），且业务逻辑直接内嵌在路由函数中。导致：

- **P1（高）GOD FILE**：无法并行开发、难测试、难定位。无 `APIRouter` 分组。
- **P2（中）旧路径未清理**：`/summary` `/events` `/tables` `/pos` `/sop` `/cost` `/iot` `/erp` `/benchmark` `/alerts/*` 等无前缀路由与 `/v1/*` 并存，ADR-004（统一 /v1）未执行。
- **P3（中）hub_core 职责过重**：`compute_store_health` / `turnover_suggestions` / `_rollup_from_rows` / `_region_worst_health` 等领域计算混在「内存状态管理」文件中。

## 2. 目标结构

```
cloud/event_hub/
├── app.py            # 组装根：建 FastAPI、建单例、include_router、startup/shutdown（~80 行）
├── runtime.py        # 新增：hub/db/alert_gateway 单例容器 + 依赖提供者
├── routers/          # 新增包，按 8 业务域拆
│   ├── __init__.py
│   ├── _deps.py      # 共享 helper：_resolve_store_id、报表权限等
│   ├── system.py     # /health /metrics /seed
│   ├── auth.py       # /auth/token /v1/auth/me
│   ├── ingest.py     # 旧 GET/POST /events /tables /pos /sop /cost /iot /erp
│   ├── receiving.py  # /v1/receiving/* /v1/audit/signatures
│   ├── sop.py        # /v1/sop/* /sop/ask
│   ├── iot.py        # /v1/iot/*
│   ├── reports.py    # /v1/reports/daily/*
│   ├── alerts.py     # /alerts/* /v1/audit/acks
│   ├── org.py        # /benchmark /v1/region/overview /v1/national/overview
│   └── admin.py      # /v1/admin/*
├── domain/           # 新增包（P3）：纯业务逻辑
│   ├── __init__.py
│   ├── health.py     # compute_store_health / _rollup_from_rows / _region_worst_health
│   └── turnover.py   # turnover_suggestions
└── hub_core.py       # 瘦身：仅 EventStore + MultiTenantHub 状态管理
```

## 3. 关键决策

### 3.1 共享状态机制（拆分命脉）

**现状**：路由函数依赖模块级全局 `hub` / `db` / `alert_gateway`；测试 fixture 靠 monkeypatch 这三个全局注入测试实例：

```python
hub_app_module.db = create_hub_database(db_path)
hub_app_module.hub = MultiTenantHub(on_persist=hub_app_module.db.on_persist)
hub_app_module.alert_gateway = AlertGateway(db_path)
```

**问题**：若 router 子模块在 import 时 `from app import hub`，则绑定的是旧引用，测试 monkeypatch 不生效。

**方案**：改用 **FastAPI 依赖注入 + 延迟绑定**。

```python
# runtime.py
from typing import Optional
hub: Optional["MultiTenantHub"] = None
db = None
alert_gateway: Optional["AlertGateway"] = None

def get_hub() -> "MultiTenantHub": return hub
def get_db(): return db
def get_alert_gateway() -> "AlertGateway": return alert_gateway

def init(hub_, db_, alert_gateway_) -> None:
    """app.py startup 调用，注入单例。"""
    global hub, db, alert_gateway
    hub, db, alert_gateway = hub_, db_, alert_gateway_
```

```python
# routers/receiving.py
from cloud.event_hub.runtime import get_hub, get_db
@router.post("/v1/receiving/submit")
def receiving_submit(body, auth=Depends(get_auth_context),
                     hub=Depends(get_hub), db=Depends(get_db)):
    ...
```

**测试迁移**：fixture 从 patch `app.hub/db/alert_gateway` 改为 patch `runtime.hub/db/alert_gateway`（或调用 `runtime.init(...)`）。每个测试约 3 行，机械替换。

### 3.2 P2 旧路径迁移（ADR-004）

- 新规范路径全部位于 `/v1/*`。
- 旧无前缀路径**保留但标记 deprecated**：`APIRouter` 路由加 `deprecated=True`（OpenAPI 标记），并在响应加 `Deprecation` 头。
- `dashboard/assets/core.js` 的 fetch 改指 `/v1/*` 对应端点；前端 fetch 集中在 core.js，单点切换。
- 过渡期双活：旧路径仍可用，避免破坏未迁移调用方。

**需要新增 /v1 别名的旧端点**（ingest + alerts + org 域）：
为旧 GET/POST `/events /tables /pos /sop /cost /iot /erp`、`/summary`、`/stores`、`/benchmark`、`/alerts/*`、`/sop/ask` 提供 `/v1/...` 规范路径，旧路径保留 deprecation。

### 3.3 P3 领域层抽取

`hub_core` 中的纯函数（吃 dict 吐 dict，无状态依赖）平移至 `domain/`：

- `domain/health.py`：`compute_store_health`、`_rollup_from_rows`、`_region_worst_health`
- `domain/turnover.py`：`turnover_suggestions`

`hub_core` 改为 import 调用。`tests/test_region_overview.py` 现 `from cloud.event_hub.hub_core import compute_store_health`——在 `hub_core` 保留 re-export（`from cloud.event_hub.domain.health import compute_store_health`）以零改测试，或同步更新 import。**选择 re-export**，减少测试改动面。

## 4. 约束（护栏）

1. **所有端点路径 + 响应结构零变化**（旧路径保留 + 新增 /v1 别名）；13 个测试文件为验收护栏。
2. **一次迁移一个 router**：迁完跑 `pytest`，绿了再迁下一个。
3. 共享 helper（`_resolve_store_id`、`_enforce_report_generate`、`_append_cost_item` 等）提至 `routers/_deps.py` 复用。
4. `app.py` startup 中的 `org_registry.apply_to_hub`、DB 水合、daily scheduler 逻辑保持不变，只是改为调用 `runtime.init(...)` 后再执行。

## 5. 迁移顺序（建议）

1. 建 `runtime.py` + `routers/_deps.py`，`app.py` 改为调用 `runtime.init`，**先不拆路由**，跑测试确认基线绿。
2. 抽 `domain/`（P3），`hub_core` re-export，跑测试。
3. 按域逐个迁路由到 `routers/*.py`，每迁一个 include_router + 跑测试。顺序：system → auth → ingest → receiving → sop → iot → reports → alerts → org → admin。
4. P2：为旧路径加 deprecation + 新增 /v1 别名，更新 `core.js`，跑测试 + 手工冒烟 `run_poc.sh`。
5. 全绿后 `app.py` 应只剩组装根。

## 6. 验收标准（DoD）

- [x] `app.py` ≤ ~120 行，仅组装根逻辑（112 行：imports + runtime.init + deprecation 中间件 + startup + 10×include_router）
- [x] 10 个 router 模块各自聚焦单一业务域（system/auth_routes/ingest/receiving/sop/iot/reports/alerts/org/admin）
- [x] `domain/` 纯函数无 FastAPI/状态依赖（health.py 73 行 · turnover.py 20 行）
- [x] `pytest` 全绿：62 passed（59 基线 + 3 新 /v1 别名测试）
- [x] uvicorn 冒烟通过：/health ok、/v1/* 正常、deprecation 头行为正确
- [x] 旧路径返回 `Deprecation: true` 头；24 条 legacy 路由 OpenAPI 标记 deprecated；/metrics、/auth/token 不受影响
- [x] `core.js` 11 处 fetch 已切换至 /v1 端点

**附加成果**：`org_registry` 纳入 runtime 容器，消除 routers→app 反向依赖；全模块 pyflakes 干净。

## 7. 非目标（本轮不做）

- 前端构建工具引入（P4）
- `rbac.json` 与 `auth.py ROLE_ACTIONS` 单一数据源统一（P4，单独 ADR）
- 边缘离线队列实现（DEV-105，独立 BL 专项）
- 旧路径的最终删除（过渡期后单独执行）
