# 组织架构覆盖度评估与修正清单

**冯校长火锅 · 智能运营 · 全国连锁组织覆盖**

| 项目 | 内容 |
|------|------|
| 版本 | V1.1 |
| 更新 | 2026-06-16 |
| 关联 | [product_design.md](product_design.md) · [product_hierarchy_national_chain.md](product_hierarchy_national_chain.md) · [task_supervision_engine_design.md](task_supervision_engine_design.md) |

---

## 1. 评估结论

现有产品已覆盖老板总览、区域下钻、店长看板、来料、SOP、安全告警、追溯雏形等主链路，覆盖度约 **70%**。主要缺口不在展示层，而在“谁负责、谁跟进、谁复核、谁只读”的组织执行闭环。

| 组织诉求 | 当前覆盖 | 缺口 | 修正 |
|----------|----------|------|------|
| 老板/总部看全国风险 | `cockpit.html`、层级看板 | 只读边界需与 Admin 写能力隔离 | ADR-009 保持观测面/管控面分离 |
| 区域/大区督导异常店 | `regional.html`、异常门店 | 缺跨模块任务督办收口 | 新增 F-TASK |
| 店长/班组执行整改 | SOP 指派、告警 ack | 任务状态散落在 SOP/告警/来料 | 统一 tasks/task_events |
| 推销/增收 | Phase 1 Won't Have | 无规则版轻量入口 | 新增 F-SALES，P2 rule-based |
| 来料到日报可追溯 | OpsEvent、签字、日报 | 缺统一 trace_id/ref_id 说明 | 新增 F-TRACE，复用 OpsEvent/task_events |
| 角色权限 | 7 类角色 + RBAC JSON | 缺班组长、营销运营、财务审计 | 新增 3 角色并纳入 data_scope |

---

## 2. 修正 A：任务督办引擎 F-TASK

结论：**需改为 P1.5 轻量内核，不抢占 BL-01~08。**

F-TASK 不做完整 L3 工作流中台，只收口四类门店执行任务：

- SOP 违规整改
- 翻台/清台督促
- critical/warn 告警跟进
- 来料异常复核

详设见 [task_supervision_engine_design.md](task_supervision_engine_design.md)。

### 2.1 Codex 评审后修订点

| 项 | 修订 |
|----|------|
| `overdue/escalated` | 作为 SLA 派生标记，不作为互斥主状态 |
| `reopen` | 仅督导/店长/总部 PMO 可从 `submitted/closed` 发起，必须写 reason 和 task_event |
| `cancel` | 创建人/店长/督导可在未 closed 前取消；closed 后仅 admin override |
| `reassign` | 必须写 task_event，并显式选择 SLA 策略：`reset_from_reassign` 或 `keep_original_due_at` |
| P1.5 排期 | 仅做轻量 kernel + SOP 兼容 + 最小 UI；feature flag 上线 |

---

## 3. 修正 B：推销/增收 F-SALES

F-SALES 从 Phase 1 Won't Have 调整为 **Phase 2 Should Have**，但仅限 rule-based 版本：

| 能力 | Phase | 边界 |
|------|-------|------|
| 桌态/时段触发的推荐话术 | P2 | 规则表 + 人工确认 |
| 会员画像与营销自动化 | P3 | 依赖会员中台，不进 P2 |
| 营销活动配置 | P2 | 仅 `marketing_ops` 可写，PMO 可审计 |

F-SALES 不应影响 Phase 1 UAT，也不应成为 IMP-402 前置条件。

---

## 4. 修正 C：全链路追溯 F-TRACE

F-TRACE 不新建大而全追溯表，复用：

- ADR-002 `OpsEvent`
- F-TASK `task_events`
- 来料 `receiving_batches/signatures`
- 日报 `daily_reports`

核心字段：

| 字段 | 用途 |
|------|------|
| `ref_type` | `ops_event` / `receiving_batch` / `table` / `sop` / `alert` |
| `ref_id` | 原始事件或业务对象 ID |
| `task_id` | 关联整改任务 |
| `trace_id` | 跨对象追溯链 ID，可由 `store_id + business_day + ref_id` 派生 |

---

## 5. 修正 D：通用餐饮集成位

Phase 1 已有 POS/IoT/ERP/VLM 接口雏形，后续集成位按“插件式适配 + OpsEvent 入 Hub”推进：

| 集成 | P1/P2 边界 |
|------|------------|
| POS | P1 只读桌态/结账信号 |
| IoT | P1 真 MQTT；P2 设备目录 |
| ERP/采购 | P1 当日 PO；P2 供应商 KPI |
| 企微/钉钉 | P1 critical 推送；P2 任务卡片 |

---

## 6. 修正 E：角色补全

新增角色必须服从 ADR-009 `data_scope`，并同步进入 `auth.py`、`rbac.json`、后端读写守卫、PRD 权限矩阵。

| 角色 | data_scope | 权限边界 |
|------|------------|----------|
| `shift_lead` / 班组长 | store | 桌态、任务 ack/reassign；不可收货提交、不可 admin 写 |
| `marketing_ops` / 营销运营 | region/zone/national | F-SALES 规则/内容；不可改 SOP/阈值/用户 |
| `finance_audit` / 财务审计 | store/region/national | 成本、追溯、日报、审计只读；不可 ack/reassign/cancel |

角色计数统一：当前实现 7 角色为店长、前厅领班、厨师长、收货员、区域督导、总部 PMO、集团决策者；PRD 中的加盟业主为 P3 角色，未进当前 `rbac.json`。

---

## 7. 排期建议

| 优先级 | 内容 | 原则 |
|--------|------|------|
| P0 | BL-01~08 UAT 阻塞清零 | 不被 F-TASK/F-SALES 抢资源 |
| P1.5 | F-TASK kernel | feature flag；可替代 DEV-421，不扩大 IMP-402 |
| P2 | F-SALES rule-based、Admin RBAC 入库 | 依赖 strict scope |
| P3 | 会员营销、加盟业主增强 | 依赖会员中台/全国化 |

