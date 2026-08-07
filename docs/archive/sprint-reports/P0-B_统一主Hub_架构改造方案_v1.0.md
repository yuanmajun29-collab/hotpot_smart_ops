# P0-B 统一主 Hub 架构改造方案

> 版本: v1.0 | 日期: 2026-08-03 | 状态: 实施中
> 基于: 审查报告严重问题#2 (D1-D3/Hub双轨)

---

## 一、问题诊断

### 当前双轨架构 (❌)

```
┌─ Edge UI 侧 (Jetson) ─────────────────────────────┐
│                                                    │
│  身份: PIN/session (6位数字)                       │
│  数据: JSON 文件缓存                               │
│  API: /api/v1/* (15个模块)                        │
│  Gateway: agent_gateway.py (可绕过)                │
│  审计: JSONL 文件                                  │
│                                                    │
│  业务逻辑:                                         │
│  ├─ product_master_api.py (货品)                   │
│  ├─ purchase_order_api.py (采购)                  │
│  ├─ receiving_api.py (收货)                        │
│  ├─ platform_api.py (平台对接)                    │
│  └─ assistant_api.py (AI助理+Gateway)             │
│                                                    │
└────────────────────────────────────────────────────┘

┌─ Cloud Hub 侧 (腾讯云) ───────────────────────────┐
│                                                    │
│  身份: JWT + RBAC (中文角色)                      │
│  数据: PostgreSQL                                 │
│  Router: 24个文件 (部分未启用)                     │
│  审计: 无统一 schema                              │
│                                                    │
│  已有但未完全启用:                                  │
│  ├─ routers/inventory.py                          │
│  ├─ routers/receiving.py                          │
│  ├─ routers/kitchen.py                            │
│  └─ auth.py + rbac.py                             │
│                                                    │
└────────────────────────────────────────────────────┘
```

### 问题清单

| # | 问题 | 严重度 | 影响 |
|---|------|:------:|------|
| 1 | **身份双轨** | 🔴 严重 | PIN vs JWT，权限无法统一 |
| 2 | **数据双轨** | 🔴 严重 | JSON缓存 vs PG，数据不一致 |
| 3 | **API双轨** | 🔴 严重 | Edge UI业务API应迁入Hub |
| 4 | **Gateway可绕过** | 🔴 严重 | ADR承认非强制 |
| 5 | **审计分散** | 🟠 高 | Edge文件+Hub无schema |
| 6 | **无correlation_id** | 🟠 高 | 无法全链路trace |

---

## 二、目标架构 (✅)

### 统一后架构

```
┌─ Browser ──→ Edge UI (纯客户端/缓存) ──→ Cloud Hub (唯一数据源)
│                │                           │
│                │ 本地功能:                 │ JWT + RBAC:
│                │ - 摄像头抓拍              │ - 店长/厨师长/督导
│                │ - 离线缓冲               │ - 区域经理/总部管理员
│                │ - UI渲染                 │
│                │                           │ PG 数据库:
│                │ 转发层:                   │ - product_master
│                │ hub_proxy.py             │ - purchase_orders
│                │ (自动故障转移)            │ - inventory
│                │                           │ - receiving_records
│                │                           │ - audit_events (append-only)
│                │                           │
│                │                           │ Gateway 中间件:
│                │                           │ - 强制不可绕过
│                │                           │ - correlation_id 串联
│                │                           │ - HIGH/CRITICAL 需审批
```

---

## 三、改造内容

### 3.1 新增文件

| 文件 | 用途 | 状态 |
|------|------|:----:|
| `hotpot_platform/cloud/event_hub/middleware/gateway.py` | Hub Gateway中间件 | ✅ 已创建 |
| `hotpot_platform/cloud/event_hub/middleware/__init__.py` | 中间件包导出 | ✅ 已创建 |
| `hotpot_platform/cloud/event_hub/middleware/audit_schema.sql` | PG审计表DDL | ✅ 已创建 |
| `hotpot_platform/cloud/event_hub/routers/supply_chain.py` | 统一供应链API | ✅ 已创建 |
| `edge/edge-ui/api/hub_proxy.py` | Edge→Hub代理层 | ✅ 已创建 |

### 3.2 修改文件

| 文件 | 修改内容 | 状态 |
|------|---------|:----:|
| `hotpot_platform/cloud/event_hub/app.py` | 集成Gateway中间件 | ✅ 已修改 |

### 3.3 核心组件说明

#### A. Hub Gateway 中间件 (`middleware/gateway.py`)

```python
# 特性:
- 拦截受控端点 (CONTROLLED_ENDPOINTS 映射表)
- 验证 JWT 权限 (从 Authorization 头提取)
- 风险分级处理:
  * LOW/MEDIUM → 放行 + 审计
  * HIGH → 需要 X-Approval-Token，否则403
  * CRITICAL → 需要多人审批
- 注入 correlation_id (全链路追踪)
- 审计缓冲 → 批量写入PG (100条/批)

# 使用方式:
app.add_middleware(HubGatewayMiddleware)
```

#### B. PG 审计 Schema (`middleware/audit_schema.sql`)

```sql
-- 5张 append-only 表:
1. audit_events        -- 审计事件主表 (核心)
2. approval_tasks      -- 审批任务表
3. operation_log       -- 操作日志 (调试用)
4. data_change_log     -- 数据变更追踪
5. rbac_change_log     -- RBAC权限变更审计

-- 视图:
v_audit_dashboard      -- 30天审计仪表盘

-- 清理策略:
cleanup_old_audit_data(90) -- 保留90天
```

#### C. 统一供应链 Router (`routers/supply_chain.py`)

```python
# 替代 Edge UI 双轨实现:
- GET    /supply-chain/products          -- 货品查询 (PG)
- POST   /supply-chain/products          -- 创建货品 (MEDIUM, 自动审计)
- POST   /supply-chain/purchase-orders   -- 采购订单 (HIGH, 需审批)
- GET    /supply-chain/purchase-orders/{id} -- 订单详情
- POST   /supply-chain/receiving         -- 收货记录 (HIGH, VLM辅助)
- POST   /supply-chain/receiving/{id}/approve -- 收货审批
- POST   /supply-chain/approvals         -- 创建审批任务
- PUT    /supply-chain/approvals/{id}/decision -- 审批决策
- GET    /supply-chain/inventory         -- 库存查询 (实时)

# 特性:
- JWT认证 (Depends(get_current_user))
- RBAC权限检查
- Gateway强制集成
- correlation_id注入
```

#### D. Edge UI 代理层 (`hub_proxy.py`)

```python
# 功能:
- HTTP请求转发到Hub (43.139.143.12:8098)
- JWT Token自动管理 (申请+刷新+缓存)
- 离线降级 (本地缓存+离线队列)
- 健康检查和故障转移

# 配置:
HubProxyConfig(
    hub_url="http://43.139.143.12:8098",
    timeout=30.0,
    retry_count=3,
    offline_mode=False,
)
```

---

## 四、迁移路径

### Phase 1: 基础设施 (当前阶段 ✅)

- [x] 创建 Gateway 中间件
- [x] 创建 PG 审计 Schema
- [x] 创建统一供应链 Router
- [x] 创建 Edge 代理层
- [x] 集成到 Hub app.py

### Phase 2: 数据迁移

- [ ] 在腾讯云 PG 执行 audit_schema.sql
- [ ] 迁移 product_master.json → PG 表
- [ ] 迁移 cameras.json → PG devices 表
- [ ] 建立数据同步机制 (Edge缓存 ← Hub PG)

### Phase 3: API 迁移

- [ ] Edge UI product_master_api.py → 标记 deprecated
- [ ] Edge UI purchase_order_api.py → 标记 deprecated
- [ ] Edge UI receiving_api.py → 标记 deprecated
- [ ] 前端 JS 改为调用 Hub API (通过代理或直连)

### Phase 4: 身份统一

- [ ] Edge UI PIN 登录 → JWT 登录 (调用 Hub /auth/login)
- [ ] 移除 PIN/session 依赖
- [ ] 统一 RBAC 角色映射

### Phase 5: 验证与收尾

- [ ] 全链路 trace 测试 (correlation_id 串联)
- [ ] Gateway 强制性验证 (尝试绕过应失败)
- [ ] 离线模式测试 (断网降级)
- [ ] 性能基准测试 (延迟 <200ms)
- [ ] 更新文档和部署脚本

---

## 五、风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|:----:|:----:|----------|
| PG 迁移数据丢失 | 低 | 高 | 先备份，双写验证 |
| Edge 离线时不可用 | 中 | 中 | 本地缓存+离线队列 |
| Gateway 性能瓶颈 | 低 | 中 | 异步缓冲+批量写入 |
| 前端兼容性破坏 | 中 | 中 | 渐进式迁移，保留旧API |
| JWT Token 泄露 | 低 | 高 | 短期token + HTTPS |

---

## 六、验收标准

### 必须达成 (P0-B Done)

- [ ] 所有 HIGH/CRITICAL 操作必须经 Gateway 且不可绕过
- [ ] 审计日志落 PG append-only 表 (非文件)
- [ ] 全链路 correlation_id 可追溯
- [ ] Edge UI 不再直接操作业务数据 (仅转发)
- [ ] JWT 为唯一身份认证方式 (无 PIN/session)
- [ ] pytest 测试全部通过 (无回归)

---

## 七、参考文档

- 审查报告: `docs/P0审查报告_20260803.md`
- ADR-001: IP-5 必须包含人工审批环节
- 最终方案第六章: AI 不自动创建正式采购订单
- PRD v5.3i: 产品定义和功能规格
