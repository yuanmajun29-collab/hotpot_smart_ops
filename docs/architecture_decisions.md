# 架构决策记录（ADR）

**Architecture Decision Records · Phase 1**

| 项目 | 内容 |
|------|------|
| 版本 | V1.1 |
| 更新 | 2026-06-16 |

---

## ADR-001：Phase 1 仅 L1+L2，不做 L3 中台

| 项 | 内容 |
|----|------|
| 状态 | **已采纳** |
| 日期 | 2026-06-15 |
| 背景 | 全国 50 店方案含总部中台；试点需 8 周内可演示 |
| 决策 | Phase 1 仅部署单店边缘 + 单实例 Hub；SOP OTA、跨店 BI、ModelHub 延后 Phase 2 |
| 后果 | 加盟只读、区域对标用 `/benchmark` 简化版；**层级看板只读（F-HQ06/07）PoC 已落地**；Admin 写能力与完整 L3 **延后 Phase 2**（见 ADR-009） |
| 关联 | PRD §12 Won't Have · product_goal_card |

---

## ADR-002：统一 OpsEvent，禁止模块私有 JSON

| 项 | 内容 |
|----|------|
| 状态 | **已采纳** |
| 日期 | 2026-06-12（PoC）· 2026-06-15 文档化 |
| 背景 | 多源（CV/IoT/POS）写入 Hub |
| 决策 | 全部经 `shared/schemas.OpsEvent`；Hub 只存 events 表 + snapshots |
| 后果 | 新集成必须扩展 event_type/metadata，不得旁路 |
| 代码 | `shared/schemas.py`, POST `/events` |

---

## ADR-003：持久化 SQLite（dev）/ PostgreSQL（staging+试点）

| 项 | 内容 |
|----|------|
| 状态 | **已采纳**（待 AR-401 确认试点默认） |
| 背景 | PoC 需零依赖启动；试点需重启不丢 |
| 决策 | `HOTPOT_DATABASE_URL` 未设置 → SQLite；设置 → PostgreSQL 同 schema |
| 后果 | docker `--profile postgres`；两店共库 tenant 隔离 |
| 代码 | `cloud/event_hub/db.py` factory |

---

## ADR-004：API 路径 — 试点保留无版本前缀，新 API 用 /v1

| 项 | 内容 |
|----|------|
| 状态 | **提议中**（AR-401 拍板） |
| 背景 | design_dev §1.4.4 目标 `/v1`；看板已对接 `/summary` |
| 决策 | 现有路径不动；`receiving/submit`、`audit/*` 等新接口走 `/v1` |
| 后果 | 下一 major 再统一迁移或双路由 |
| 文档 | [architecture_api_spec.md](architecture_api_spec.md) |

---

## ADR-005：边缘推理默认 yolo，dev 可用 mock

| 项 | 内容 |
|----|------|
| 状态 | **提议中** |
| 背景 | mock 便于 CI；试点需真实 CV |
| 决策 | 生产 `HOTPOT_DETECTOR_BACKEND=yolo`；CI/培训 `mock` |
| 后果 | DEV-410 切换 + 准确率报告 |
| 代码 | `edge/detector/hotpot_detector.py` |

---

## ADR-006：告警推送 — critical 企微，warn 首月仅看板

| 项 | 内容 |
|----|------|
| 状态 | **已采纳**（对齐产品 N-05） |
| 背景 | 产品原则 P1 少而准 |
| 决策 | `AlertGateway.should_push`：critical 必推；warn 需 `HOTPOT_PUSH_WARN=1` |
| 后果 | 店长概念测试确认后可能调整店级配置 |
| 文档 | [push_notification_templates.md](push_notification_templates.md) |

---

## ADR-007：HTML 看板为 Phase 1 UI 交付源

| 项 | 内容 |
|----|------|
| 状态 | **已采纳**（产品 D-001） |
| 背景 | Figma 18 Frame 未齐；HTML 15 页已可演示 |
| 决策 | 架构侧看板通过静态 `dashboard/` + Hub REST；Phase 2 可选 TS 重构 |
| 后果 | 无 SSR/BFF；CORS/鉴权直连 Hub |
| 关联 | product_design_changelog D-001 |

---

## ADR-008：离线队列 SQLite 边缘侧（24h）

| 项 | 内容 |
|----|------|
| 状态 | **提议中** |
| 背景 | 设计原则断网 24h |
| 决策 | 边缘 `edge/queue/` SQLite 缓存 OpsEvent，恢复后 bulk POST Hub |
| 后果 | DEV-105 实现与压测 |
| 差距 | poc_to_production_gap §2 平台 |

---

## ADR-009：全国组织层级与 data_scope 模型

| 项 | 内容 |
|----|------|
| 状态 | **已采纳** |
| 日期 | 2026-06-16 |
| 背景 | 全国连锁需自上而下看板与管控；Phase 1 仅 2 店试点但需可扩展 |
| 决策 | 组织四级：`org → zone → region → store`；JWT/RBAC 含 `data_scope`（store/region/zone/national）；**观测面**（层级看板）与**管控面**（Admin）分离；P1 静态 JSON，P2 入库 + Admin API |
| 后果 | `stores.json` 过渡；P2 新增 `orgs/zones/regions/stores/users/roles` 表与 `/v1/admin/*`；Hub 中间件强制 scope |
| 关联 | [product_hierarchy_national_chain.md](product_hierarchy_national_chain.md) · [architecture_hierarchy_phase_plan.md](architecture_hierarchy_phase_plan.md) |

---

## ADR-010：F-TASK 轻量任务督办引擎

| 项 | 内容 |
|----|------|
| 状态 | **提议中** |
| 日期 | 2026-06-16 |
| 背景 | SOP 指派、告警 ack、来料异常、翻台督促分散，组织执行缺少统一闭环 |
| 决策 | P1.5 新增 `tasks` + `task_events` 轻量任务内核；`overdue/escalated` 作为 SLA 派生标记，不作为主状态；`sop_assignments` 迁移为兼容视图/写入路径 |
| 权限 | `reopen` 仅店长/督导/PMO 且必须 reason；`cancel` 未 closed 前由创建人/店长/督导执行，closed 后仅 admin override；`reassign` 必须写 task_event 和 `sla_policy` |
| SLA | `reassign` 必须显式选择 `reset_from_reassign` 或 `keep_original_due_at`，禁止隐式重置 |
| 后果 | 可替代 DEV-421；不抢占 BL-01~08；不开启 feature flag 时旧 SOP 指派行为不变 |
| 关联 | [task_supervision_engine_design.md](task_supervision_engine_design.md) · ADR-009 |

---

## ADR-011：F-SALES 规则版增收/推销

| 项 | 内容 |
|----|------|
| 状态 | **提议中** |
| 日期 | 2026-06-16 |
| 背景 | 组织目标包含推销/增收，但 Phase 1 不宜引入会员营销复杂度 |
| 决策 | F-SALES 从 Phase 1 Won't Have 调整为 Phase 2 Should Have，仅做 rule-based 推销建议、话术库和人工确认任务；会员画像/会员自动化延后 P3 |
| 权限 | `marketing_ops` 可按 region/zone/national scope 维护 F-SALES 规则；不可修改 SOP、阈值、用户、门店 |
| 后果 | 可生成 F-TASK 任务；不进入 Phase 1 UAT，不作为 IMP-402 前置 |
| 关联 | [org_hierarchy_coverage_assessment.md](org_hierarchy_coverage_assessment.md) · ADR-009/010 |

---

## ADR-012：F-TRACE 复用事件与任务的追溯链

| 项 | 内容 |
|----|------|
| 状态 | **提议中** |
| 日期 | 2026-06-16 |
| 背景 | 来料、SOP、告警、日报已有事件与签字记录，但缺少统一追溯链 |
| 决策 | 不新建大而全追溯表；复用 ADR-002 `OpsEvent`、ADR-010 `task_events`、来料签字和日报记录，通过 `ref_type/ref_id/trace_id` 串联查询 |
| 权限 | `finance_audit` 只读成本、追溯、日报、审计；不可 ack/reassign/cancel |
| 后果 | 降低迁移风险；P2 可先做查询 API，P3 再接 BI/数据湖 |
| 关联 | ADR-002 · ADR-009 · ADR-010 |

---

## 变更流程

1. 新 ADR 追加本文，状态：提议中 → 已采纳 / 已废弃  
2. AR-401 / Sprint Review 可晋升「提议中」→「已采纳」  
3. 重大变更同步 [architecture_changelog.md](architecture_changelog.md)
