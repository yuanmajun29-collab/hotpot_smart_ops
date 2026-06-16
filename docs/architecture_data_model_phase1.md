# Phase 1 数据模型

**OpsEvent · 持久化 · 规划实体**

| 项目 | 内容 |
|------|------|
| 版本 | V1.1 |
| 代码 | `shared/schemas.py` · `cloud/event_hub/db.py` · `pg_db.py` |
| 更新 | 2026-06-16 |
| 对齐 | [architecture_api_spec.md](architecture_api_spec.md) · [task_supervision_engine_design.md](task_supervision_engine_design.md) |

---

## 1. 统一事件 OpsEvent

所有子系统产出同一结构（`shared/schemas.py`）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| event_id | UUID string | 自动 | 全局唯一 |
| event_type | string | ✅ | 业务类型，见 §2 |
| source | string | ✅ | vision / iot / pos / system |
| level | string | ✅ | info / warn / critical |
| store_id | string | ✅ | 租户 |
| message | string | ✅ | 人类可读摘要 |
| timestamp | ISO8601 | 自动 | UTC |
| zone | string | | front / kitchen / storage / receiving |
| table_id | string | | 桌号 |
| confidence | float | | 0~1 |
| metadata | object | | 扩展；含 `ref_type`/`ref_id`/`trace_id`（F-TRACE，见 §7） |

**设计原则**：禁止各模块私有 JSON 直写 Hub；扩展走 `metadata`。

---

## 2. event_type 词表（Phase 1）

| 域 | 类型常量 | 示例 event_type |
|----|----------|-----------------|
| 桌态 | TABLE_STATES | 状态变更事件 |
| 后厨穿戴 | KITCHEN_VIOLATIONS | kitchen_no_hat, kitchen_smoke |
| IoT 告警 | IOT_ALERT_TYPES | cold_chain_high, gas_leak |
| SOP | SOP_EVENT_TYPES | sop_violation, sop_completed |
| 成本 | COST_EVENT_TYPES | cost_weight_short, cost_quality_reject |
| 全链路 | IOT_LIFECYCLE_EVENTS | iot_weight_short, iot_door_open_timeout |

---

## 3. 桌态 TableState

| 字段 | 说明 |
|------|------|
| table_id | T01~T08（可配置） |
| state | empty \| dining \| need_clean \| checkout |
| confidence | CV 置信度 |
| updated_at | ISO8601 |

存储：`store_snapshots` kind=`tables` 或内存聚合。

---

## 4. 已实现表结构

### 4.1 events

| 列 | SQLite/PG | 说明 |
|----|-----------|------|
| event_id | TEXT PK | |
| store_id | TEXT | 索引 |
| level | TEXT | |
| source | TEXT | |
| payload | TEXT/JSONB | 完整 OpsEvent JSON |
| created_at | TEXT/TIMESTAMPTZ | 索引 DESC |

保留：每店最多 500 条热数据（`MAX_EVENTS_PER_STORE`），超出滚动。

### 4.2 store_snapshots

| 列 | 说明 |
|----|------|
| store_id + kind | PK；kind 如 tables, sop, cost, pos, erp, iot |
| payload | JSON 快照 |
| updated_at | |

### 4.3 alert_pushes / alert_acks（AlertGateway SQLite 侧车）

| 表 | 用途 |
|----|------|
| alert_pushes | 企微推送记录 |
| alert_acks | ack 人、时间、note |

路径：`demo/data/alert_push.log` + DB 表（gateway 内）。

---

## 5. Phase 1 业务表（已实现或打桩）

| 表 | 用途 | DEV | Phase |
|----|------|-----|-------|
| `receiving_batches` | PDA 验收批次 | DEV-419 | 1 ✅ |
| `receiving_signatures` | 双人签字 | DEV-420 | 1 ✅ |
| `sop_assignments` | 违规指派（过渡） | DEV-421 | 1 ✅ |
| `daily_reports` | 日报 Markdown + meta | DEV-423 | 1 ✅ |
| `iot_readings` | 时序温湿度 | DEV-412 | 1 ✅ 打桩 |

### 5.1 receiving_batches（草案）

| 列 | 类型 | 说明 |
|----|------|------|
| batch_id | TEXT PK | RCV-xxx |
| store_id | TEXT | |
| po_id | TEXT | ERP PO |
| sku | TEXT | |
| weight_kg | REAL | 实收 |
| po_weight_kg | REAL | PO |
| variance_pct | REAL | |
| vlm_grade | TEXT | A/B/C/D |
| temp_c | REAL | 探针 |
| status | TEXT | submitted / rejected |
| created_at | TIMESTAMPTZ | |

### 5.2 receiving_signatures

| 列 | 说明 |
|----|------|
| batch_id | FK |
| role | receiver / chef |
| signed_by | 用户名 |
| signed_at | |

### 5.3 sop_assignments

| 列 | 说明 |
|----|------|
| assignment_id | PK |
| store_id | |
| sop_id | |
| assignee | |
| due_at | |
| status | open / done / verified |

> **P1.5 迁移**：`sop_assignments` 平滑迁入 `tasks`（`task_type=sop_violation`）；旧表只读或作兼容视图（ADR-010）。

### 5.4 tasks（P1.5 规划 · DEV-520）

| 列 | 类型 | 说明 |
|----|------|------|
| task_id | TEXT PK | |
| store_id | TEXT | 租户 |
| task_type | TEXT | sop_violation / cleaning / safety_alert / … |
| priority | TEXT | P0 / P1 / P2 |
| status | TEXT | pending / in_progress / submitted / closed / cancelled |
| source | TEXT | manual / system |
| ref_type | TEXT | ops_event / sop / alert / receiving_batch / table |
| ref_id | TEXT | 关联业务 ID |
| assignee_id | TEXT | 责任人 |
| assignee_group | TEXT | 班组（可选） |
| created_by | TEXT | |
| title | TEXT | |
| detail | TEXT | 回执正文 |
| due_at | TIMESTAMPTZ | SLA 截止 |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

`is_overdue` / `is_escalated` **不落库**，查询时派生（ADR-010）。

### 5.5 task_events（P1.5 规划 · DEV-520）

| 列 | 说明 |
|----|------|
| event_id | PK |
| task_id | FK → tasks |
| action | create / accept / start / submit / verify / cancel / reopen / reassign / escalated |
| actor_id | 操作人 |
| from_status | 可选 |
| to_status | 可选 |
| note | reason、reassign sla_policy 等 |
| ts | ISO8601 |

---

## 6. Phase 2 组织与管控表（规划）

> 规格：[architecture_hierarchy_phase_plan.md §2](architecture_hierarchy_phase_plan.md#22-phase-1-过渡当前) · DEV-501~503

| 表 | 用途 | PRD |
|----|------|-----|
| `orgs` | 品牌/集团根 | F-HQ08 |
| `zones` | 大区 | F-HQ08 |
| `regions` | 区域 | F-HQ08 |
| `stores` | 门店（含 zone_id/region_id/status） | F-HQ08 |
| `users` | 账号 | F-HQ09 |
| `roles` | 角色定义 | F-HQ10 |
| `role_permissions` | 菜单/操作/data_scope | F-HQ10 |
| `user_store_scopes` | 用户可访问门店 | F-HQ09 |
| `admin_audit_log` | 配置变更审计 | F-HQ11 |
| `sales_rules` | F-SALES 规则版 | F-SALES02 | DEV-529 |

Phase 1 过渡：`demo/data/stores.json` + `auth.py` DEMO_USERS + `rbac.json`。

---

## 7. 追溯字段（F-TRACE）

不新建大而全追溯表（ADR-012）。跨对象串联字段：

| 字段 | 位置 | 说明 |
|------|------|------|
| `ref_type` | OpsEvent.metadata / tasks | `ops_event` / `receiving_batch` / `table` / `sop` / `alert` |
| `ref_id` | 同上 | 原始业务对象 ID |
| `trace_id` | 同上 / 查询参数 | 跨链路 ID；可派生 `store_id + business_day + ref_id` |
| `task_id` | receiving_batches / 告警详情 | 关联整改任务 |

P2 查询 API：`GET /v1/trace/{trace_id}`（DEV-530）聚合 OpsEvent + task_events + 签字 + 日报。

---

## 8. 店级配置（JSON，非 DB）

路径：`demo/data/stores/<store_id>/`

| 文件 | 内容 |
|------|------|
| seed.json | 灌库初始数据 |
| sop_signals_noon.json | SOP 输入信号 |
| live/*.json | 管道运行时产物 |

**生产目标** `config.json`（见 design_dev §1.3.1）：

```json
{
  "store_id": "store_yuhuan",
  "store_name": "冯校长火锅·玉环店",
  "cameras": [{ "id": "front_01", "rtsp": "rtsp://...", "rois": [] }],
  "iot_gateway": { "mqtt_broker": "mqtt://127.0.0.1:1883", "topics": [] },
  "hub_url": "http://10.1.12.17:8088",
  "model_version": "table_v1.0.0"
}
```

DEV-407/408 交付两店正式 config。

---

## 9. 存储选型（Phase 1）

| 数据 | 试点推荐 | 全国目标 |
|------|----------|----------|
| 事件+快照 | PostgreSQL（staging）/ SQLite（dev） | PostgreSQL |
| IoT 时序 | Hub 快照 + 可选 iot_readings 表 | TimescaleDB |
| 截图 | 本地目录 demo | OSS |
| 推送日志 | SQLite 侧车 | PG 表 |

**ADR**：见 [architecture_decisions.md](architecture_decisions.md) ADR-003。

---

## 10. ER 关系（扩展）

```mermaid
erDiagram
    STORE ||--o{ OPS_EVENT : emits
    STORE ||--o{ TABLE_STATE : has
    STORE ||--o{ RECEIVING_BATCH : receives
    RECEIVING_BATCH ||--o{ RECEIVING_SIGNATURE : signed_by
    STORE ||--o{ SOP_ASSIGNMENT : tracks_legacy
    STORE ||--o{ TASK : owns
    TASK ||--o{ TASK_EVENT : logs
    TASK }o--o| OPS_EVENT : ref
    STORE ||--o{ ALERT_ACK : acknowledges
    ZONE ||--o{ REGION : contains
    REGION ||--o{ STORE : contains
```

---

## 11. 变更记录

| 版本 | 日期 | 说明 |
|------|------|------|
| V1.1 | 2026-06-16 | tasks/task_events、组织表 P2、F-TRACE 字段；与 api_spec/ADR-010~012 对齐 |
| V1.0 | 2026-06-15 | OpsEvent + Phase 1 表初版 |
