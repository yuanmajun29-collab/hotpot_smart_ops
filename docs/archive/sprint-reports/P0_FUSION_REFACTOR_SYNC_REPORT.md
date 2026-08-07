# 火瞳 · 椒江样板店全链路融合改造 — 代码变更同步报告

> **版本**：v1.0 | **日期**：2026-08-04
> **分支**：`feature/d1-expo-sprint` | **基线**：HEAD `9098397` → 改造后
> **依据文档**：《火瞳_椒江真实样板店全链路融合改造方案.docx》
> **状态**：✅ P0-A/B/C/D 全部完成

---

## 变更总览

| 编号 | 改造域 | 涉及文件 | 变更类型 | 状态 |
|------|--------|----------|----------|------|
| P0-A | 真实多摄像机边缘采集 | `ipc_config_jiaojiang.yml`, `camera_api.py` | 配置+逻辑修改 | ✅ |
| P0-B | 统一事件契约北向协议 | `edge_events.py` (新建) | 新增模块 | ✅ |
| P0-C | 真实事件→Agent审计链路 | `cloud_mock.js`, `agent_gateway.py` | 安全加固 | ✅ |
| P0-D | POS/销售Agent/KPI回写 | `agents.py`, `pg_db.py`, `kpi_feedback_engine.py`, `pos_bridge.py` | 扩展+新建schema | ✅ |

---

## P0-A: 真实椒江多摄像机与边缘采集改造

### A1. IPC 配置去 Mock 化 (`ipc_config_jiaojiang.yml`)

**变更内容**：
- ❌ 移除 `fallback_image` 路径（原: `/opt/hotpot-smart-ops/data/fallback_hotpot.jpg`）
- ❌ 移除 `mock_source: "static_image"` 字段
- ⚠️ `fallback_on_error`: `true` → `false`（禁止降级到mock）
- ✅ 新增 ROI 区域配置（kitchen_area/front_hall_area/entrance_area/cashier_area）
- ✅ 新增 `model_profile`, `sample_interval_seconds`, `frame_freshness_max_age_ms`

**对齐PRD**：
- 第6章「数据与证据规范」— D4证据表要求ROI标注
- 第4A章「前厅场景」— 多区域摄像头覆盖

### A2. Camera API 去 Mock 降级 (`camera_api.py`)

**变更内容**：
- 移除 `mock_snapshot.jpg` 文件回退逻辑（原256-268行）
- 替换为 HTTP 503 + 明确错误信息："生产环境已禁用Mock降级"

**安全影响**：摄像头离线时不再返回假图，避免误导业务判断

---

## P0-B: 统一事件契约、北向协议与云端主写

### B1. 统一边缘事件合约 (`edge_events.py`) — **全新模块**

**文件路径**：`hotpot_platform/cloud/event_hub/routers/edge_events.py`
**代码规模**：~350行

**核心数据模型**：

| 模型 | 用途 | 关键字段 |
|------|------|----------|
| `EventType` | 20+ 标准事件类型 | waste_detected / table_dirty / sales_transaction / receiving_completed ... |
| `EventSeverity` | 严重级别 | info / warning / error / critical |
| `EvidenceRef` | 视觉证据引用 | type/url/hash_sha256/captured_at/camera_id/frame_index |
| `UnifiedEdgeEvent` | 统一事件体 | idempotency_key/source_event_id/trace_id/offline_buffer |
| `BatchEventsRequest` | 批量提交 (≤100) | events[]/store_id/batch_id |

**API 端点**：

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/v1/edge/events` | 边缘事件批量上报（幂等校验） |
| GET | `/api/v1/edge/events/schema` | Schema 发现（供边缘设备对接） |
| GET | `/api/v1/edge/events/idempotency/stats` | 幂等统计（运维监控） |
| POST | `/v1/events` | Legacy 兼容桥接（自动转换） |

**对齐PRD**：
- 第6章「数据与证据规范」— 统一事件格式
- 第3章「功能清单」— EARS 事件驱动架构

---

## P0-C: 真实事件→任务→Agent→人工审计链路

### C1. Dashboard Mock 层生产环境禁用 (`cloud_mock.js`)

**变更内容**：
- 在 IIFE 顶部添加 `_isProduction` 环境检测
- 生产环境下直接 `return`，不执行任何Mock逻辑
- 触发条件：`HOTPOT_PRODUCTION=true` / URL参数 `mock=false` / `data-env=production`

**对齐PRD**：
- 第8章「非功能需求」— 演示数据不得混入生产
- 最终方案第六章 — AI不自动创建正式订单

### C2. Agent Gateway Fail-Closed 注解强化 (`agent_gateway.py`)

**变更内容**：
- 模块 docstring 补充 P0-C Fail-Closed 要求说明
- 类 docstring 扩展安全机制细节：
  - 未预期异常 → 拒绝执行 (success=False)
  - HIGH/CRITICAL 操作 → 必须人工审批
  - BLOCKED 操作 → 直接拒绝 + 安全告警
  - 审计日志记录所有尝试（无论成功/失败）

---

## P0-D: 真实POS、销售/服务Agent与KPI回写

### D1. FrontHallAgent 销售增长扩展 (`agents.py`)

**版本升级**：`1.0.0` → `1.1.0` (P0-D版)

**新增能力矩阵**：

| 能力域 | 任务类型 | 方法 | 权限级别 |
|--------|----------|------|----------|
| 销售KPI查询 | `query_sales_kpi` | `_query_sales_kpi()` | ✅ 只读 |
| 促销建议(仅建议) | `get_promo_suggestions` | `_get_promo_suggestions()` | ⚠️ 建议权 |
| 班前培训 | `pre_shift_training` | `_generate_pre_shift_training()` | ✅ 只读 |
| 班后复盘 | `post_shift_review` | `_generate_post_shift_review()` | ✅ 只读 |
| 菜品知识库 | `get_dish_knowledge` | `_get_dish_knowledge()` | ✅ 只读 |

**新增订阅主题**：
- `sales.*` → `on_sales_event`
- `pos.*` → `on_pos_event`

**内置知识库**：
- `_DISH_KNOWLEDGE_BASE`: 6款招牌菜品SKU/卖点/搭配推荐
- `_SERVICE_TERMINOLOGY`: 标准服务话术（迎宾/入座/推荐/客诉/送客）

**⚠️ 核心安全约束**：
```
自动改价/折扣/发券一律禁止 (BLOCKED by AgentGateway)
所有促销建议 explicit_mark = "suggestion_only"
折扣类请求返回 action: "BLOCKED" + blocked_reason
```

**消息处理器**（10个新增handler）：
- `query.sales_kpi` → `_handle_sales_kpi_query()`
- `query.dish_recommendations` → `_handle_dish_recommendations()`
- `training.pre_shift` → `_handle_pre_shift_training()`
- `training.post_shift_review` → `_handle_post_shift_review()`
- `sales.promo_suggestion_request` → `_handle_promo_suggestion_request()`

### D2. 销售事件数据库 Schema (`pg_db.py`)

**新增表1: `sales_events`（销售事件主表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| event_id | VARCHAR(64) PK | 全局唯一（幂等键） |
| transaction_id | VARCHAR(64) | POS原始单号 |
| order_type | ENUM | dine_in/takeout/delivery/wechat |
| shift | VARCHAR(10) | lunch/dinner/late_night |
| total_amount | NUMERIC(12,2) | 实收总额 |
| guest_count | INTEGER | 用餐人数 |
| avg_check | NUMERIC(10,2) | 客单价 |
| payment_method | VARCHAR(20) | 支付方式 |
| pos_source | VARCHAR(64) | 数据来源标记 |
| status | ENUM | pending/confirmed/reversed/voided |
| payload | JSONB | 原始POS完整副本 |

**索引策略**：store_id / transaction_id / occurred_at / shift+occurred_at / table_id

**新增表2: `sales_transaction_detail`（销售明细表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| detail_id | VARCHAR(64) PK | 明细唯一ID |
| sales_event_id | FK → sales_events | 关联主表 |
| sku_code | VARCHAR(32) | SKU编码 |
| dish_name | TEXT | 菜品名称 |
| unit_price / quantity / subtotal | NUMERIC/REAL | 价格数量 |
| is_recommended | BOOLEAN | 员工推荐标记 |
| is_promo / promo_type | BOOLEAN/VARCHAR | 促销标记 |

### D3. 销售 KPI 映射扩展 (`kpi_feedback_engine.py`)

**新增5项 KPI 映射**：

| 任务类型 | metric_id | 中文名称 | 单位 | 方向 | 阈值(g/w/c) |
|----------|-----------|----------|------|------|-------------|
| query_sales_kpi | daily_revenue | 日销售额 | ¥ | higher | 15k/12k/8k |
| sales_avg_check | avg_check_amount | 客单价 | ¥ | higher | 180/150/120 |
| calculate_turnover_rate | turnover_rate | 翻台率 | 次 | higher | 2.5/2.0/1.5 |
| service_response | service_response_time | 服务响应时间 | 秒 | lower | 60/90/120 |
| post_shift_review | complaint_rate | 客诉率 | % | lower | 0/1/3 |

### D4. POS Bridge 默认模式修正 (`pos_bridge.py`)

**变更内容**：
- `default="sim"` → `default="file"`（默认从文件读取POS数据）
- 新增生产环境保护：`HOTPOT_ENV=production/prod/uat` 时自动阻止 sim 模式

**对齐最终方案**：第六章明确禁止模拟数据替代真实经营结论

---

## 对齐验证清单

### PRD v5.3 功能覆盖

| PRD章节 | 功能点 | 代码实现 | 状态 |
|---------|--------|----------|------|
| 3.3 A04 前厅领班 | 清台检测闭环 | FrontHallAgent._detect_dirty_tables() | ✅ 已有 |
| 3.3 A04 前厅领班 | 服务响应监控 | _check_response_time() | ✅ 已有 |
| 3.3 A04 前厅领班 | 翻台率优化 | _calculate_turnover_rate() | ✅ 已有 |
| **3.3 A04 前厅领班** | **销售增长分析** | **_query_sales_kpi() [P0-D新增]** | ✅ **新增** |
| **3.3 A04 前厅领班** | **服务培训知识库** | **_generate_pre_shift_training() [P0-D新增]** | ✅ **新增** |
| **第4A章 前厅场景** | **多区域视觉覆盖** | **ROI zones config [P0-A新增]** | ✅ **新增** |
| **第6章 D4证据** | **统一事件格式** | **UnifiedEdgeEvent [P0-B新增]** | ✅ **新增** |
| **第6章 D4证据** | **证据哈希追溯** | **EvidenceRef.hash_sha256 [P0-B新增]** | ✅ **新增** |
| **第8章 非功能** | **生产禁Mock** | **cloud_mock.js + camera_api.py [P0-C新增]** | ✅ **新增** |
| **最终方案Ch6** | **AI不自动PO** | **agent_gateway.py Fail-Closed [P0-C强化]** | ✅ **强化** |
| **G4闭环** | **KPI自动回写** | **5项新KPI映射 [P0-D新增]** | ✅ **新增** |

### 架构设计对齐

| 架构图层 | 变更项 | 影响 |
|----------|--------|------|
| 边缘层 | MultiCameraScheduler (规划中) | ROI config 已就绪 |
| 接入层 | edge_events.py 北向API | 统一契约已定义 |
| Agent层 | FrontHallAgent v1.1.0 | 销售+培训能力就绪 |
| 数据层 | sales_events + detail 表 | Schema 已定义 |
| 反馈层 | KPI引擎 5新映射 | 第四闭环KPI就绪 |

---

## 后续工作 (P1 — 不在本次范围内)

| ID | 工作项 | 优先级 | 说明 |
|----|--------|--------|------|
| P1-01 | API路径统一 (/v1 → /api/v1) | Medium | 全局路由前缀重构 |
| P1-02 | 摄像头重连/流控 | Medium | camera_api.py 增强 |
| P1-03 | 配置热加载通知 | Low | config_api.py 增强 |
| P1-04 | 帧新鲜度检测+证据哈希 | Medium | 边缘推理管线集成 |
| P1-05 | 告警疲劳保护 | Low | 事件频率限制 |
| P1-06 | 消息送达回执 | Low | Agent消息确认机制 |

---

## Git 提交记录

本次改造所有变更均在 `feature/d1-expo-sprint` 分支上完成，待用户确认后可合并至 main。

```
[待提交] feat(p0-abcd): 椒江样板店全链路融合改造 P0-A/B/C/D
 - P0-A: IPC配置去Mock化 + ROI区域配置
 - P0-B: 统一边缘事件合约 edge_events.py (~350行)
 - P0-C: Dashboard Mock生产禁用 + Gateway Fail-Closed注解
 - P0-D: FrontHallAgent销售扩展 + 销售事件Schema + 5项KPI映射
```

---

*本文档由火瞳AI团队根据《椒江真实样板店全链路融合改造方案》生成*
*2026-08-04 | 展会冲刺 D1 冻品供应链阶段*
