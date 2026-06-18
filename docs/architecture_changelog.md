# 架构设计变更日志

**Architecture Changelog · Phase 1**

---

## V1.5 · 2026-06-19

| 变更 | 说明 |
|------|------|
| `architecture_design_phase1.md` V1.2 | C-05 从“来料成本”升级为“来料成本 / 损耗预测 lead loop”，新增 loss-risk 规划接口与可解释性 NFR |
| `architecture_api_spec.md` | PRD 主映射新增 F-C06~07 → 规划 `/v1/cost/loss-risk` + `/v1/sop/assign*` |
| `architecture_data_model_phase1.md` | 新增 P1B 损耗预测规划实体，强调先复用 snapshots/OpsEvent、再落 `loss_features/loss_predictions` |
| `architecture_decisions.md` | 新增 ADR-016：Phase 1 创业切入口以后厨损耗预测为 lead loop |

---

## V1.4 · 2026-06-16

| 变更 | 说明 |
|------|------|
| `architecture_design_phase1.md` V1.1 | 四产品面、rollup/Admin stub、实现矩阵、AR-401 结论 |
| 新增 `ar401_review_outcome_20260616.md` | 文档层 **有条件通过** |
| 对齐 | PRD V1.5 · api/data V1.1 · development_delivery_plan |

---

## V1.3 · 2026-06-16

| 变更 | 说明 |
|------|------|
| 新增 `development_delivery_plan.md` | 与 product 索引互链；HLD/LLD/DB/测试主计划 |

---

## V1.2 · 2026-06-16

| 变更 | 说明 |
|------|------|
| `architecture_api_spec.md` V1.1 | 全量 API 目录、F-EXEC01/F-HQ12、Admin stub、P1.5 tasks |
| `architecture_data_model_phase1.md` V1.1 | tasks/task_events、组织表、F-TRACE 字段 |
| DEV 编号 | sprint §12.1.1~12.1.2 与 product_hierarchy/task 详设统一 |
| `architecture_design_index.md` | §1.2 产品↔架构对齐检查表 |

---

## V1.1 · 2026-06-16

| 变更 | 说明 |
|------|------|
| ADR-013 | 设计先行、实现与真数据接入分期；三轨道治理规则 |
| `architecture_design_index.md` §1.1 | 设计/实现/接入三轨道图与评审要点 |
| 关联 | product_design.md V1.3 §2 P8、§2.1 |

---

## V1.0 · 2026-06-15

### 新增文档体系

| 文档 | 说明 |
|------|------|
| `architecture_design_index.md` | 架构文档索引与 DoD |
| `architecture_design_phase1.md` | Phase 1 架构规格主文档 |
| `architecture_api_spec.md` | REST API 目录与 /v1 规划 |
| `architecture_data_model_phase1.md` | OpsEvent、表结构、规划表 |
| `architecture_deployment_phase1.md` | docker/systemd/两店拓扑 |
| `architecture_decisions.md` | ADR-001~008 |
| `architecture_review_checklist.md` | AR-401 评审清单 |
| `architecture_review_outcome_template.md` | 会后回填模板 |
| `ar401_code_directory_mapping.md` | 会前代码目录 vs §2.5 映射 |
| `ar401_meeting_invite_20260618.md` | AR-401 邀请定稿 6/18 10:00 |
| `ar401_meeting_agenda_20260618.html` | 可打印议程 |

### 与 PoC 代码对齐

- API 目录对齐 `cloud/event_hub/app.py` 22+ 路由
- 数据表对齐 `db.py` / `pg_db.py` events + store_snapshots
- 部署对齐 `docker-compose.yml` profiles

### 待 AR-401 拍板

- ADR-004 API /v1 策略
- ADR-003 试点默认 PG vs SQLite
- ADR-005 生产 CV 后端默认值
- ADR-008 离线队列实现优先级

---

## AR-401 评审结论（会后粘贴）

| 结论 | ☐ 通过　☐ 有条件通过　☐ 不通过 |
| 日期 | |

<!-- 使用 architecture_review_outcome_template.md 对应场景块 -->

---

## 架构修订记录

| 日期 | ADR/模块 | 变更 | 作者 |
|------|----------|------|------|
| | | | |
