# 产品设计变更日志

**Changelog · Phase 1**

---

## V1.5 · 2026-06-16

| 变更 | 说明 |
|------|------|
| `product_design.md` V1.4 | F-EXEC01、F-HQ12/API 分工、§9.1 角色实现状态 |
| `product_hierarchy_national_chain.md` V1.2 | F-EXEC01 归 P1；DEV 编号统一 |
| 对齐 | `architecture_api_spec` V1.1 · `architecture_data_model` V1.1 · sprint §12.1 |

---

## V1.4 · 2026-06-16

| 变更 | 说明 |
|------|------|
| `product_design.md` V1.3 | §2 新增 P8；§2.1 设计完整性 vs 分期交付 |
| 对齐 ADR-013 | 产品与架构「终局写全、落地分期」总原则 |

---

## V1.3 · 2026-06-16

| 变更 | 说明 |
|------|------|
| 新增 `product_completeness_review.md` | 业务平台多租户登录 + 运营后台 CRUD 完整性复盘 |

---

## V1.2 · 2026-06-16

| 变更 | 说明 |
|------|------|
| 新增 `product_hierarchy_national_chain.md` | 全国连锁 L0~L3 层级、双产品面（看板/Admin）、F-HQ08~13、P1~P4 分阶段 |
| 新增 `architecture_hierarchy_phase_plan.md` | 组织 ER、Admin API、Hub scope、研发里程碑 DEV-501~506 |
| 更新 `product_design.md` V1.2 | §5.9 层级看板、§5.10 Admin、§6.5 IA、§12.3 Won't Have 修订 |
| 更新 `architecture_decisions.md` | ADR-009 组织层级；ADR-001 后果修订 |
| 更新 `architecture_api_spec.md` | §7 Phase 2 Admin API 规划 |
| 更新 index | product_design_index · architecture_design_index |

---

## V1.2 · 2026-06-15

| 变更 | 说明 |
|------|------|
| 新增 `pm401_review_outcome_template.md` | PM-401 通过/有条件通过/不通过 三套 changelog+DoD 回填模板 |
| 更新 `product_design_changelog.md` | 反馈区拆分 PM-401 / PM-402 |
| 更新 `product_design_index.md` | 会后回填路径与阶段 OK 判定 |

---

## V1.1 · 2026-06-15

### 文档体系完善

| 变更 | 说明 |
|------|------|
| 新增 `product_design_index.md` | 产品设计文档总索引与阶段 DoD |
| 新增 `product_goal_card.md` | 一页目标卡 + 五项目标差距里程碑 |
| 新增 `phase1_mvp_acceptance_checklist.md` | Must Have 五列验收表 + UAT 脚本 |
| 新增 `product_review_checklist.md` | PM-401 产品评审可执行清单 |
| 新增 `uat_concept_test_record.md` | PM-402 店长概念测试/UAT 记录模板 |
| 新增 `push_notification_templates.md` | 企微五类卡片文案定稿 |
| 更新 `sprint_task_backlog.md` V1.2 | §6.1 UAT 阻塞 DEV-408~426 + PM-401/402 |

### 设计策略决策

| 决策 ID | 内容 | 理由 |
|---------|------|------|
| **D-001** | Phase 1 以 **HTML 看板为交互原型源**，Figma 高保真与 Dev Mode 标注作为 **对齐交付**，不阻塞研发联调 | PoC 已拆 15 页 HTML；试点时间紧 |
| **D-002** | 首月试点 **warn 默认不推手机**（N-05），与店长概念测试后再开 | PRD P1 原则 |
| **D-003** | Go-Live 门槛 = 验收表 §5 八条阻塞清零 + §6 UAT 可勾选 | 与 IMP-402 对齐 |

### PRD 修订（product_design.md V1.1）

- 新增 §14 实现状态快照、§15 产品设计交付 DoD
- 附录 B 扩展文档关系
- 「下一步建议」改为可执行清单并链到新文档

### Figma 规格修订（figma_component_spec.md V1.1）

- §4 Frame 状态更新：Web/PDA 多数标记为「HTML 原型可对齐」
- 新增 §10 HTML→Figma 对齐说明

### 用户故事地图（user_story_map.md V1.1）

- 新增 §9 Release 1 用户故事实现状态表

### 待执行（未改代码）

- PM-401 定于 2026-06-17 — ICS 已含腾讯会议占位号 888-888-888 / 密码 061717，见 [product_meetings_tencent.md](product_meetings_tencent.md)
- PM-402 两店店长概念测试 — **玉环 6/19 10:00 · 椒江 6/20 10:00**，邀请见 [pm402_meeting_invite_20260619_20.md](pm402_meeting_invite_20260619_20.md)（评审通过后发送）
- 设计师 Figma 18 Frame 与 HTML 对齐（或书面确认 D-001）

---

## V1.0 · 2026-06-12

| 文档 | 说明 |
|------|------|
| product_design.md V1.0 | PRD 初版：F-xxx 功能规格、§12 MVP 范围 |
| user_story_map.md | 33 条 US + 概念测试脚本 |
| figma_component_spec.md | Design Token + 组件 + Frame 清单 |
| solution.md V2.0 | 业务方案 17 章 |
| design_dev_implementation_plan.md | 三合一主计划 |
| sprint_task_backlog.md V1.0 | Sprint 1~4 DEV 任务 |

---

## 反馈回填区（概念测试后填写）

### PM-401 评审结论（会后粘贴，模板见 [pm401_review_outcome_template.md](pm401_review_outcome_template.md)）

| 结论 | ☐ 通过　☐ 有条件通过　☐ 不通过 |
| 日期 | |
| 修订项数 | |

<!-- 将 pm401_review_outcome_template.md 场景 A/B/C 对应块粘贴到下方 -->

---

### PM-402 概念测试反馈

| 日期 | 店 | 反馈摘要 | 修订文档 | 状态 |
|------|-----|----------|----------|------|
| | 玉环 | | | ☐ 待处理 |
| | 椒江 | | | ☐ 待处理 |
