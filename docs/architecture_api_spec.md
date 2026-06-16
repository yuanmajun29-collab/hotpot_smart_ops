# API 规格

**Event Hub · 试点 REST API · 与 PRD 对齐**

| 项目 | 内容 |
|------|------|
| 版本 | V1.1 |
| 服务 | `cloud/event_hub/app.py` |
| Base URL | `http://<host>:8088` |
| 鉴权 | `Authorization: Bearer <jwt>` · 边缘 `X-API-Key` · demo 模式宽松 |
| 对齐 | [product_design.md §5](product_design.md#5-功能规格feature-prd) · [architecture_hierarchy_phase_plan.md §3](architecture_hierarchy_phase_plan.md#3-api-分层) |

---

## 1. 版本策略

| 阶段 | 前缀 | 说明 |
|------|------|------|
| **PoC 遗留** | 无（`/summary` 等） | 看板已对接，Phase 1 保留 |
| **Phase 1+** | `/v1/*` | 新接口直接 `/v1`（ADR-004） |
| **兼容** | 旧路径保留 1 个版本周期 | `/v1/sop/assign` → P1.5 可代理到 `/v1/tasks` |

---

## 2. 已实现 API（Phase 1）

### 2.1 平台与认证

| 方法 | 路径 | 说明 | PRD | 状态 |
|------|------|------|-----|:----:|
| GET | `/health` | 健康检查、db_backend | F-H01 | ✅ |
| GET | `/metrics` | 运行指标 | F-H01 | ✅ |
| POST | `/auth/token` | 登录换 Token | — | ✅ |
| GET | `/v1/auth/me` | 当前用户 + role + data_scope + can_admin | F-HQ10 | ✅ demo |
| GET | `/stores` | 门店列表 | — | ✅ |
| POST | `/seed` | 灌演示数据 | — | ✅ dev |

### 2.2 读模型（门店看板）

| 方法 | 路径 | 说明 | PRD |
|------|------|------|-----|
| GET | `/summary` | 单店聚合摘要 | F-H02 |
| GET | `/events` | 事件流 `?level=&limit=` | F-A01 |
| GET | `/tables` | 桌态列表 | F-T01 |
| GET | `/sop` | SOP 评估结果 | F-S01 |
| GET | `/cost` | 成本摘要 | F-C01 |
| GET | `/iot` | IoT 摘要 | F-K01 |
| GET | `/pos` | POS 统计 | F-T03 |
| GET | `/erp` | ERP PO 列表 | F-P01 |

### 2.3 写模型（边缘/集成）

| 方法 | 路径 | 说明 | 调用方 |
|------|------|------|--------|
| POST | `/events` | 单条/批量 OpsEvent | vision_worker, mqtt |
| POST | `/tables` | 桌态覆盖 | 边缘/人工 |
| POST | `/sop` | SOP 结果写入 | scheduler |
| POST | `/cost` | 成本批次 | ERP bridge |
| POST | `/iot` | IoT 生命周期 | ingredient bridge |
| POST | `/pos` | POS 事件 | pos_bridge |
| POST | `/erp` | ERP 收货 | erp_bridge |

### 2.4 告警

| 方法 | 路径 | 说明 | PRD | 状态 |
|------|------|------|-----|:----:|
| GET | `/alerts/push-log` | 企微推送日志 | F-A04 | ✅ |
| GET | `/alerts/routes` | webhook 配置状态（脱敏） | DEV-414 | ✅ |
| POST | `/alerts/test-push` | 发送测试卡片 | DEV-414 | ✅ |
| GET | `/alerts/acks` | ack 列表 | F-A03 | ✅ |
| POST | `/alerts/ack` | 确认告警 | F-A03 | ✅ |
| GET | `/alerts/escalations` | 未 ack 升级 | F-A05 | ✅ |

### 2.5 智能与日报

| 方法 | 路径 | 说明 | PRD | 状态 |
|------|------|------|-----|:----:|
| POST | `/sop/ask` | SOP RAG 问答 | F-S07 | ✅ |
| POST | `/v1/reports/daily/generate` | 触发日报（可选 push 企微） | F-R01 | ✅ |
| GET | `/v1/reports/daily` | 历史日报 `?report_date=` | F-R01 | ✅ |

### 2.6 PDA · 来料 · IoT · SOP 指派

| 方法 | 路径 | 说明 | DEV | PRD | 状态 |
|------|------|------|-----|-----|:----:|
| POST | `/v1/receiving/submit` | PDA 验收入库+签字 | DEV-419 | F-P06 | ✅ |
| GET | `/v1/receiving/batches` | 当日批次 | DEV-419 | F-C01 | ✅ |
| GET | `/v1/iot/readings` | 温湿度时序 | DEV-412 | F-K01 | ✅ 打桩 |
| POST | `/v1/iot/readings/batch` | 边缘批量写入 | DEV-412 | F-K01 | ✅ 打桩 |
| POST | `/v1/sop/assign` | 违规指派 | DEV-421 | F-S04 | ✅ |
| GET | `/v1/sop/assignments` | 整改工单列表 | DEV-421 | F-S04 | ✅ |
| PUT | `/v1/sop/assignments/{id}/status` | 工单状态 | DEV-421 | F-S04 | ✅ |
| GET | `/v1/audit/acks` | 督导审计 ack | DEV-422 | F-A03 | ✅ |
| GET | `/v1/audit/signatures` | 签字审计 | DEV-422 | F-S05 | ✅ |

> P1.5：`/v1/sop/assign*` 作为 **F-TASK 兼容适配层** 保留；新能力走 `/v1/tasks/*`（§3）。

### 2.7 层级 · 战略观测（只读）

| 方法 | 路径 | 说明 | PRD | Phase | 状态 |
|------|------|------|-----|-------|:----:|
| GET | `/benchmark` | 区域对标（兼容别名） | F-HQ01 | 1 | ✅ |
| GET | `/v1/region/overview` | 区域/大区总揽 `?region_id=` | F-HQ06/07 | 1 | ✅ |
| GET | `/v1/national/overview` | 全国 rollup KPI + 异常店 | **F-EXEC01** · F-HQ12 | 1 API / 2 UI | ✅ |

**F-EXEC01 vs F-HQ12**：

- **F-EXEC01**（`cockpit.html`）：P1 战略驾驶仓 v1，消费 `/v1/national/overview`，只读摘要。
- **F-HQ12**（`national.html`）：P2 独立全国总揽页（多大区 Tab、完整 IA）；**复用同一 API**，不新增后端契约。

### 2.8 Admin v0.1 打桩（Phase 1 过渡 · 非生产 CRUD）

| 方法 | 路径 | 说明 | PRD | Phase | 状态 |
|------|------|------|-----|-------|:----:|
| GET | `/v1/admin/org-tree` | 组织树只读 | F-HQ08 | 1 stub | ✅ |
| GET | `/v1/admin/stores` | 门店列表 | F-HQ08 | 1 stub | ✅ |
| POST | `/v1/admin/stores` | 增店（内存/registry） | F-HQ08 | 1 stub | ⚠️ |
| PUT | `/v1/admin/stores/{id}` | 改店 | F-HQ08 | 1 stub | ⚠️ |
| GET | `/v1/admin/users` | 用户列表（demo） | F-HQ09 | 1 stub | ⚠️ |
| GET | `/v1/admin/audit-logs` | 门店变更审计 | F-HQ11 | 1 stub | ⚠️ |
| GET | `/v1/admin/pipeline/status` | 数据流打桩状态 | — | 1 | ✅ |
| POST | `/v1/admin/pipeline/tick` | 触发打桩 tick | — | 1 | ✅ |

**Phase 2** 完整 Admin CRUD 见 §4.1；P1 不以 Admin 写能力作为 Go-Live 门槛。

### 2.9 VLM 服务（独立进程 :8089）

| 方法 | 路径 | 说明 | PRD |
|------|------|------|-----|
| GET | `/health` | 健康 | — |
| POST | `/review` | 来料/清台图像复核 | F-C03 |

---

## 3. Phase 1.5 规划 API（F-TASK · feature flag）

> 详设：[task_supervision_engine_design.md §8](task_supervision_engine_design.md#8-api-设计v1tasks) · DEV-520~524

| 方法 | 路径 | 说明 | PRD | Phase |
|------|------|------|-----|-------|
| POST | `/v1/tasks` | 创建任务 | F-TASK01 | 1.5 |
| GET | `/v1/tasks` | 列表 `?status=&type=&assignee=&overdue=` | F-TASK01 | 1.5 |
| GET | `/v1/tasks/{id}` | 详情 + task_events 时间线 | F-TASK03 | 1.5 |
| POST | `/v1/tasks/{id}/assign` | 派办 | F-TASK01 | 1.5 |
| POST | `/v1/tasks/{id}/accept` | 认领（写 event，不改主状态） | F-TASK01 | 1.5 |
| POST | `/v1/tasks/{id}/start` | pending → in_progress | F-TASK01 | 1.5 |
| POST | `/v1/tasks/{id}/submit` | 提交回执 | F-TASK01 | 1.5 |
| POST | `/v1/tasks/{id}/verify` | 复核关闭 | F-TASK01 | 1.5 |
| POST | `/v1/tasks/{id}/cancel` | 取消 | F-TASK03 | 1.5 |
| POST | `/v1/tasks/{id}/reopen` | 重开（须 reason） | F-TASK03 | 1.5 |
| POST | `/v1/tasks/{id}/reassign` | 转派 + `sla_policy` | F-TASK03 | 1.5 |
| GET | `/v1/region/tasks/overview` | 区域任务 rollup | F-TASK12 | 2 |

`overdue` / `escalated` 为查询派生标记，非主状态（ADR-010）。

---

## 4. Phase 2 规划 API

### 4.1 Admin · RBAC（生产级）

| 方法 | 路径 | 说明 | PRD | DEV |
|------|------|------|-----|-----|
| GET/POST/PUT | `/v1/admin/zones` | 大区 CRUD | F-HQ08 | DEV-501 |
| GET/POST/PUT | `/v1/admin/regions` | 区域 CRUD | F-HQ08 | DEV-501 |
| GET/POST/PUT/DELETE | `/v1/admin/stores` | 门店 CRUD（DB） | F-HQ08 | DEV-502 |
| GET/POST/PUT | `/v1/admin/users` | 用户 CRUD | F-HQ09 | DEV-503 |
| GET/POST/PUT | `/v1/admin/roles` | 角色 CRUD | F-HQ10 | DEV-503 |
| GET/PUT | `/v1/admin/roles/{id}/permissions` | 权限矩阵 | F-HQ10 | DEV-503 |
| GET | `/v1/admin/audit-logs` | 配置审计（DB） | F-HQ11 | DEV-505 |

### 4.2 增收 · 追溯

| 方法 | 路径 | 说明 | PRD | DEV |
|------|------|------|-----|-----|
| GET/POST/PUT | `/v1/sales/rules` | F-SALES 规则版话术/触发 | F-SALES01~03 | DEV-529 |
| GET | `/v1/trace/{trace_id}` | 追溯链查询 | F-TRACE01~02 | DEV-530 |

**鉴权（Phase 2 strict）**：`HOTPOT_AUTH_MODE=strict`；JWT `data_scope` + `scope_ids[]`；写操作需对应 `admin:*` / `sales:rule:write` / `trace:read`。

---

## 5. 请求/响应约定

### 5.1 OpsEvent（POST `/events`）

```json
{
  "event_type": "table_need_clean",
  "source": "vision",
  "level": "warn",
  "store_id": "store_yuhuan",
  "message": "T03 待清台",
  "zone": "front",
  "table_id": "T03",
  "confidence": 0.92,
  "metadata": {}
}
```

必填：`event_type`, `source`, `level`, `store_id`, `message`  
枚举见 `shared/schemas.py`：`EventLevel`, `EventSource`, `TABLE_STATES`

**追溯扩展（F-TRACE · P2）**：`metadata.ref_type`、`metadata.ref_id`、`metadata.trace_id` 可选；见 [architecture_data_model_phase1.md §7](architecture_data_model_phase1.md#7-追溯字段-f-trace)。

### 5.2 租户

- Query：`?store_id=store_yuhuan`
- Header：`X-Store-Id: store_yuhuan`
- JWT claims：`store_id`, `role`, `data_scope`, `scope_ids[]`

### 5.3 错误码

| HTTP | 含义 |
|------|------|
| 401 | 未鉴权 |
| 403 | 跨店/跨 scope |
| 404 | 门店/资源不存在 |
| 409 | 任务状态机非法流转 |
| 422 | OpsEvent 校验失败 |
| 503 | Hub 不可用 |

---

## 6. 与产品功能追溯（主映射）

| PRD | 主要 API | Phase |
|-----|----------|-------|
| F-H01~02 | `/health`, `/metrics`, `/summary` | 1 |
| F-T01~03 | `/tables`, `/summary`, `/pos` | 1 |
| F-K01~04 | `/iot`, `/events`, `/v1/iot/readings*` | 1 |
| F-S01~05 | `/sop`, `/sop/ask`, `/v1/sop/assign*` | 1 |
| F-C01~04 | `/cost`, `/erp`, VLM `/review`, `/v1/receiving/*` | 1 |
| F-A01~04 | `/events`, `/alerts/*`, `/v1/audit/acks` | 1 |
| F-R01~02 | `/v1/reports/daily*` | 1 |
| F-P01~06 | `/erp`, `/v1/receiving/*` | 1 |
| F-HQ01 | `/benchmark` | 1 |
| F-HQ06/07 | `/v1/region/overview` | 1 |
| **F-EXEC01** | `/v1/national/overview` + `cockpit.html` | 1 |
| F-HQ12 | `/v1/national/overview` + `national.html` | 2 UI |
| F-HQ08~11 | `/v1/admin/*` | 1 stub → 2 DB |
| F-TASK01~04 | `/v1/tasks/*` + sop 兼容 | 1.5 |
| F-SALES01~03 | `/v1/sales/rules` | 2 |
| F-TRACE01~02 | `/v1/trace/{trace_id}` | 2 |

---

## 7. OpenAPI

- 当前：FastAPI 自动生成 `/docs`、`/openapi.json`
- Phase 1 DoD：导出冻结版 `docs/openapi_phase1.yaml`（AR-401 后）

---

## 8. 变更记录

| 版本 | 日期 | 说明 |
|------|------|------|
| V1.1 | 2026-06-16 | 与 PRD/层级计划对齐：已实现 API 归档、F-EXEC01/F-HQ12 双挂、Admin stub、P1.5 tasks、P2 sales/trace |
| V1.0 | 2026-06-15 | Phase 1 初版 |
