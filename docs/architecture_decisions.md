# 架构决策记录（ADR）

**Architecture Decision Records · Phase 1**

| 项目 | 内容 |
|------|------|
| 版本 | V1.0 |
| 更新 | 2026-06-15 |

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

## 变更流程

1. 新 ADR 追加本文，状态：提议中 → 已采纳 / 已废弃  
2. AR-401 / Sprint Review 可晋升「提议中」→「已采纳」  
3. 重大变更同步 [architecture_changelog.md](architecture_changelog.md)
