# AR-401 架构评审结论 · 文档对齐复核

**与 PRD V1.5 / development_delivery_plan 同步**

| 项目 | 内容 |
|------|------|
| 版本 | V1.0 |
| 日期 | 2026-06-16 |
| 结论 | **有条件通过（文档层）** |
| 关联 | [architecture_design_phase1.md](architecture_design_phase1.md) · [architecture_api_spec.md](architecture_api_spec.md) · [architecture_data_model_phase1.md](architecture_data_model_phase1.md) |

---

## 1. 评审结论

| 域 | 判定 | 说明 |
|----|------|------|
| L1+L2 边界（ADR-001） | ✅ | Phase 1 单 Hub；L3 Admin DB 延 P2 |
| OpsEvent 统一（ADR-002） | ✅ | 全链路经 Hub events |
| 四类产品面（ADR-009） | ✅ | :3000 执行/观测 · :3001 Admin |
| API 契约（api_spec V1.1） | ✅ | 与 PRD §6 映射一致 |
| 数据模型（data_model V1.1） | ✅ | P1 表 + P1.5 tasks + P2 组织 |
| 任务引擎（ADR-010） | ✅ | P1.5 规划；SOP 兼容路径明确 |
| 真数据 / 部署 | ⚠️ | BL-01~08 待关闭；AR-401 现场拍板待 6/18 |

---

## 2. 架构文档同步项（本轮完成）

| 文档 | 更新 |
|------|------|
| `architecture_design_phase1.md` | V1.1 · 四产品面 · 观测/管控 · 实现矩阵 |
| `architecture_api_spec.md` | V1.1 · 已实现 + P1.5/P2 规划 |
| `architecture_data_model_phase1.md` | V1.1 · tasks/组织/追溯 |
| `architecture_hierarchy_phase_plan.md` | V1.3 · DEV 统一 |
| `development_delivery_plan.md` | V1.0 · 同步机制 + HLD/LLD/测试 |
| ADR-001~013 | 013 设计分期原则 |

---

## 3. ADR 拍板（文档层 · 待 6/18 会议确认）

| ADR | 文档层建议 | 会议拍板 |
|-----|------------|----------|
| ADR-003 | staging 默认 PostgreSQL | ☐ |
| ADR-004 | 新 API 走 /v1，旧路径保留 | ☐ |
| ADR-005 | 生产 CV：yolo；dev/CI：mock | ☐ |
| ADR-008 | 边缘离线队列 DEV-105 优先级 | ☐ |
| ADR-010 | F-TASK P1.5 feature flag | ✅ 文档已采纳 |

---

## 4. 六闭环真数据断点（不变）

| ID | 断点 | DEV |
|----|------|-----|
| C-01 | CV mock | DEV-408~410 |
| C-02 | IoT/告警 mock | DEV-411~414 |
| C-03 | IoT sim | DEV-412 |
| C-04 | SOP seed | 现场信号 |
| C-05 | ERP/POS bridge | DEV-413~419 |
| C-06 | 日报 | DEV-423 ✅ API |

---

## 5. DoD 更新

| # | 交付物 | 状态 |
|---|--------|------|
| 逻辑架构 Phase 1 | ✅ V1.1 文档 |
| API + 数据模型 | ✅ V1.1 |
| 产品↔架构对齐 §1.2 | ✅ 7/7 |
| 正式 AR-401 会议签字 | ⬜ 待 6/18 |
| ADR 提议中→已采纳 | ⬜ 会议拍板 |

---

## 6. 下一步

1. 6/18 AR-401 正式会议：ADR-003/004/005/008 拍板
2. 研发 BL 专项与 [development_delivery_plan §7](development_delivery_plan.md#7-开发--测试--验证--回归) 测试回归
3. openapi_phase1.yaml 导出（DoD #3）
