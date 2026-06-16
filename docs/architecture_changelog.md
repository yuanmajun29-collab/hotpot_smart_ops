# 架构设计变更日志

**Architecture Changelog · Phase 1**

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
