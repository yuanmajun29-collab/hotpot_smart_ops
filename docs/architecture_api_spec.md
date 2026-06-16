# Phase 1 API 规格

**Event Hub · 试点 REST API**

| 项目 | 内容 |
|------|------|
| 版本 | V1.0 |
| 服务 | `cloud/event_hub/app.py` |
| Base URL | `http://<host>:8088` |
| 鉴权 | `Authorization: Bearer <jwt>` · 边缘 `X-API-Key` · demo 模式宽松 |

---

## 1. 版本策略

| 阶段 | 前缀 | 说明 |
|------|------|------|
| **PoC 当前** | 无（`/summary`） | 看板已对接，保持不变至 Phase 1 末 |
| **Phase 1 目标** | `/v1/*` 别名或迁移 | AR-401 拍板；新 API 直接 `/v1` |
| **兼容** | 旧路径保留 1 个版本周期 | 双写路由或 301 |

**建议（待 AR-401）**：试点内维持现状路径，新增 `receiving/submit`、`sop/assign`、`audit/*` 走 `/v1`。

---

## 2. 已实现 API 目录

### 2.1 平台

| 方法 | 路径 | 说明 | 鉴权 | 状态 |
|------|------|------|:----:|:----:|
| GET | `/health` | 健康检查、db_backend | 无 | ✅ |
| GET | `/metrics` | 运行指标 | JWT | ✅ |
| POST | `/auth/token` | 登录换 Token | 无 | ✅ |
| GET | `/stores` | 门店列表 | JWT | ✅ |
| GET | `/benchmark` | 区域对标（兼容） | JWT（督导/总部） | ✅ |
| GET | `/v1/region/overview` | 区域/大区总揽 · `region_id=zone_east_china` | F-HQ06/07 | ✅ |
| POST | `/seed` | 灌演示数据 | 限制 | ✅ dev |

### 2.2 读模型（看板）

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

| 方法 | 路径 | 说明 | PRD |
|------|------|------|-----|
| GET | `/alerts/push-log` | 企微推送日志 | F-A04 | ✅ |
| GET | `/alerts/routes` | webhook 配置状态（脱敏） | DEV-414 | ✅ |
| POST | `/alerts/test-push` | 发送测试卡片 | DEV-414 | ✅ |
| GET | `/alerts/acks` | ack 列表 | F-A03 |
| POST | `/alerts/ack` | 确认告警 | F-A03 |
| GET | `/alerts/escalations` | 未 ack 升级 | F-A05 |

### 2.5 智能

| 方法 | 路径 | 说明 | PRD |
|------|------|------|-----|
| POST | `/sop/ask` | SOP RAG 问答 | F-S07 |

### 2.6 VLM 服务（独立进程 :8089）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康 |
| POST | `/review` | 来料/清台图像复核 |

---

## 3. Phase 1 待实现 API（UAT 阻塞）

| 方法 | 路径 | 说明 | DEV | PRD |
|------|------|------|-----|-----|
| POST | `/v1/receiving/submit` | PDA 验收入库+签字 | DEV-419 | F-P06 | ✅ |
| GET | `/v1/receiving/batches` | 当日批次 | DEV-419 | F-C01 | ✅ |
| GET | `/v1/iot/readings` | 温湿度时序 | DEV-412 | F-K01 | ✅ 打桩 |
| POST | `/v1/iot/readings/batch` | 边缘批量写入 | DEV-412 | F-K01 | ✅ 打桩 |
| POST | `/v1/sop/assign` | 违规指派 | DEV-421 | F-S04 | ✅ |
| GET | `/v1/sop/assignments` | 整改工单列表 | DEV-421 | F-S04 | ✅ |
| PUT | `/v1/sop/assignments/{id}/status` | 工单状态 | DEV-421 | F-S04 | ✅ |
| GET | `/v1/audit/acks` | 督导审计 ack | DEV-422 | F-A03 | ✅ |
| GET | `/v1/audit/signatures` | 签字审计 | DEV-422 | F-S05 | ✅ |
| POST | `/v1/reports/daily/generate` | 触发日报（可选 push 企微） | DEV-423/424 | ✅ |
| GET | `/v1/reports/daily` | 历史日报（支持 `?report_date=`） | DEV-423 | ✅ |

---

## 4. 请求/响应约定

### 4.1 OpsEvent（POST `/events`）

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

### 4.2 租户

- Query：`?store_id=store_yuhuan`
- Header：`X-Store-Id: store_yuhuan`
- JWT claims：`store_id`, `role`

### 4.3 错误码（目标）

| HTTP | 含义 |
|------|------|
| 401 | 未鉴权 |
| 403 | 跨店访问 |
| 404 | 门店/资源不存在 |
| 422 | OpsEvent 校验失败 |
| 503 | Hub 不可用 |

---

## 5. 与产品功能追溯

| PRD 模块 | 主要 API |
|----------|----------|
| F-H01~02 | `/health`, `/metrics`, `/summary` |
| F-T01~03 | `/tables`, `/summary`, `/pos` |
| F-K01~04 | `/iot`, `/events`, `/summary` |
| F-S01~05 | `/sop`, `/sop/ask`, 待 assign/sign |
| F-C01~04 | `/cost`, `/erp`, VLM `/review` |
| F-A01~04 | `/events`, `/alerts/*` |
| F-R01~02 | 待 reports API |
| F-P01~06 | `/erp`, 待 receiving/submit |
| F-HQ06/07 | `/v1/region/overview`, `/benchmark` |

---

## 7. Phase 2 规划 API（Admin · 未实现）

> 规格：[architecture_hierarchy_phase_plan.md §3.2](architecture_hierarchy_phase_plan.md#32-规划phase-2--admin)

| 方法 | 路径 | 说明 | PRD | Phase |
|------|------|------|-----|-------|
| GET/POST/PUT | `/v1/admin/zones` | 大区 CRUD | F-HQ08 | 2 |
| GET/POST/PUT | `/v1/admin/regions` | 区域 CRUD | F-HQ08 | 2 |
| GET/POST/PUT/DELETE | `/v1/admin/stores` | 门店 CRUD | F-HQ08 | 2 |
| GET/POST/PUT | `/v1/admin/users` | 用户 CRUD | F-HQ09 | 2 |
| GET/POST/PUT | `/v1/admin/roles` | 角色 CRUD | F-HQ10 | 2 |
| GET/PUT | `/v1/admin/roles/{id}/permissions` | 权限矩阵 | F-HQ10 | 2 |
| GET | `/v1/admin/audit-logs` | 配置审计 | F-HQ11 | 2 |
| GET | `/v1/national/overview` | 全国总揽 | F-HQ12 | 2 |
| GET | `/v1/auth/me` | 当前用户 + scope + 权限 | F-HQ10 | 2 |

**鉴权**：`HOTPOT_AUTH_MODE=strict`；JWT `data_scope` + `scope_ids[]`；写操作需 `admin:*` 权限。

---

## 6. OpenAPI

- 当前：FastAPI 自动生成 `/docs`、`/openapi.json`
- Phase 1 DoD：导出冻结版 `docs/openapi_phase1.yaml`（AR-401 后）
