# AR-401 架构设计评审清单

**Phase 1 试点 · 玉环 / 椒江 · 架构评审**

| 项目 | 内容 |
|------|------|
| 任务 ID | AR-401 |
| 建议时长 | 2~2.5h |
| 前置 | 产品 PRD 规格可读 · [product_goal_card.md](product_goal_card.md) |
| 主文档 | [design_dev_implementation_plan.md §1](design_dev_implementation_plan.md#第一篇设计方案) |
| 差距输入 | [poc_to_production_gap.md](poc_to_production_gap.md) |
| 索引 | [architecture_design_index.md](architecture_design_index.md) |
| 邀请 | [ar401_meeting_invite_20260618.md](ar401_meeting_invite_20260618.md) · **6/18 10:00** |
| 建议时间 | PM-401（6/17）后 · **6/18 10:00**（已定） |

---

## 1. 参会与材料

| 角色 | 必参 | 会前材料 |
|------|:----:|----------|
| 架构师 / 研发负责人 | ✅ | §1.2~1.4 + 代码目录 |
| 后端 | ✅ | `cloud/event_hub/app.py` API 列表 |
| 算法 / 边缘 | ✅ | `edge/detector/`、`edge/iot_mock/` |
| DevOps | ✅ | `docker-compose.yml`、`deploy/systemd/` |
| 产品 | ✅ | PRD §12 Must Have |
| PMO | 建议 | product_goal_card |
| 区域 IT | 建议 | pilot_deployment_checklist_direct |

| # | 会前检查 | 完成 |
|---|----------|:----:|
| 1 | PoC 演示环境可跑（Hub + 看板） | ☐ |
| 2 | `pytest` 通过情况已知 | ☐ |
| 3 | 两店 config 路径确认 `demo/data/stores/` | ☐ |
| 4 | gap 清单 P0 项已标负责人 | ☐ |

---

## 2. 架构目标与边界（15min）

| # | 评审问题 | 结论 |
|---|----------|------|
| T1 | Phase 1 是否确认 **L1 边缘 + L2 单 Hub**，不做 L3 中台？ | ☐ 是 ☐ 修订 |
| T2 | 六闭环 C-01~C06 是否全部纳入试点？ | ☐ 是 ☐ 裁剪 |
| T3 | 设计原则（边缘优先、断网 24h、OpsEvent 统一）是否采纳？ | ☐ 是 ☐ 修订 |
| T4 | 50 店全国架构是否作为 **Phase 2+ 演进**，不阻塞试点？ | ☐ 是 |

---

## 3. 逻辑架构走查（30min）

对照 [architecture_design_index.md §3](architecture_design_index.md#3-逻辑架构phase-1-试点范围) 白板过一遍：

| # | 组件 | 设计 | PoC 代码 | 结论 | 备注 |
|---|------|------|----------|------|------|
| L1-1 | RTSP / VideoIngest | §1.3.1 | `edge/stream/` | ☐ OK ☐ 缺口 | |
| L1-2 | TableDetector CV | yolo/rknn | `edge/detector/` mock 默认 | ☐ | |
| L1-3 | IoT Agent MQTT | §1.3.1 | `edge/iot_mock/` | ☐ | |
| L1-4 | IngredientBridge | §1.3.1 | `edge/iot_mock/ingredient_*` | ☐ | |
| L1-5 | 离线队列 EdgeQueue | DEV-105 | 设计有/部分实现 | ☐ | |
| L2-1 | Event Hub | FastAPI+PG | `cloud/event_hub/` | ☐ | |
| L2-2 | SOP Engine | §1.3.2 | `cloud/sop/` | ☐ | |
| L2-3 | Alert Gateway | §1.3.2 | `cloud/alert_gateway/` | ☐ | |
| L2-4 | VLM / LLM 服务 | 云端 API | `cloud/vlm_review/` `llm_report/` | ☐ | |
| L2-5 | POS / ERP 集成 | IntHub | `cloud/integrations/` mock | ☐ | |
| UI | 看板 | dashboard/ | HTML 多页 | ☐ | |

---

## 4. 数据与 API（40min）

### 4.1 OpsEvent 模型

| # | 检查项 | 参考 | 结论 |
|---|--------|------|------|
| D1 | `shared/schemas.py` 字段满足 §1.4.1 | event_id/type/source/level/store_id | ☐ |
| D2 | 各模块是否统一走 OpsEvent（禁止私有 JSON） | 代码抽查 | ☐ |
| D3 | 事件 level 与产品告警分级一致 | PRD §8 | ☐ |

### 4.2 存储

| # | 检查项 | 设计 | PoC | Phase 1 拍板 |
|---|--------|------|-----|--------------|
| D4 | 事件持久化 | PostgreSQL | SQLite 可切换 | ☐ PG ☐ SQLite 试点 |
| D5 | ack / 签字 / 推送日志表 | PG 表 | 部分有 | ☐ |
| D6 | IoT 时序 | TimescaleDB | 未上 | ☐ Phase1 简化 ☐ 上 TS |
| D7 | 视频截图 OSS | §1.4.3 | 本地/demo | ☐ Phase1 本地 ☐ OSS |

### 4.3 API

| # | 检查项 | 结论 |
|---|--------|------|
| D8 | 是否 Phase 1 统一 `/v1` 前缀 | ☐ 是 ☐ 维持现状后迁移 |
| D9 | 现有 `/summary` `/events` 与 §1.4.4 差异可接受 | ☐ |
| D10 | 新增 API 已规划：`/receiving/submit` `/sop/assign` `/audit/*` | ☐ |
| D11 | OpenAPI 文档可对外（研发/集成方） | ☐ |

**演示**：`curl http://10.1.12.17:8088/health` · `/metrics` · `/summary?store_id=store_yuhuan`

---

## 5. 六闭环数据流（30min）

每项：**设计路径 → 当前断点 → DEV 任务**

| 闭环 | 数据流 | 断点 | DEV/BL | 结论 |
|------|--------|------|--------|------|
| C-01 翻台 | RTSP→CV→Hub←POS | mock CV/POS | BL-01 DEV-408~410 | ☐ |
| C-02 后厨 | RTSP+IoT→Hub→告警 | mock IoT | BL-02 DEV-411~413 | ☐ |
| C-03 全链路 | IoT Bridge→Hub | mock | DEV-207 | ☐ |
| C-04 SOP | IoT+VLM+人工→SOP | 指派/签字未入库 | BL-05 DEV-420~421 | ☐ |
| C-05 成本 | IoT+ERP→成本 | PDA 未打通 | BL-04 DEV-416~419 | ☐ |
| C-06 日报 | Hub→LLM | 无 22:00 任务 | BL-06 DEV-423~424 | ☐ |

---

## 6. 部署与安全（25min）

| # | 检查项 | 参考 | 结论 |
|---|--------|------|------|
| S1 | 单店拓扑 RK3588 + POE + MQTT | solution §11 | ☐ |
| S2 | docker-compose 试点够用 | `docker-compose.yml` | ☐ |
| S3 | systemd 边缘守护 | `deploy/systemd/` | ☐ |
| S4 | HTTPS staging | DEV-103 | ☐ |
| S5 | JWT + API Key + store 隔离 | DEV-102 DEV-425 | ☐ |
| S6 | 密钥不入库（.env / 密钥管理） | ☐ |
| S7 | 视频留存与隐私角度 | 法务+试点清单 | ☐ |
| S8 | 4G 断网备份（加盟/直营要求） | §1.5.1 | ☐ Phase1 可选 |

---

## 7. 差距清单 P0 关闭计划（20min）

从 [poc_to_production_gap.md](poc_to_production_gap.md) 勾选 Phase 1 必须关闭项：

| # | P0 差距 | 负责人 | 目标 Sprint/周 | 签字 |
|---|---------|--------|----------------|------|
| G1 | 真实 CV + RTSP | 算法+嵌入式 | W1~W2 | |
| G2 | 真实 IoT MQTT | 嵌入式 | W1 | |
| G3 | PostgreSQL 生产默认 | 后端 | S1 已完成？确认 | |
| G4 | 企微推送生产 | 后端+DevOps | W1 | |
| G5 | PDA/签字/审计 API | 后端+前端 | W2 | |
| G6 | 离线队列 24h | 嵌入式 | W1~W2 | |
| G7 | HTTPS + 鉴权强化 | DevOps+后端 | W2 | |

---

## 8. 评审结论

| 结论 | ☐ 通过　☐ 有条件通过　☐ 不通过 |

### 架构修订项（有条件通过必填）

| # | 域 | 修订 | 责任人 | 截止 | DEV |
|---|-----|------|--------|------|-----|
| 1 | | | | | |
| 2 | | | | | |

### 与产品 PRD 冲突项（须产品确认）

| # | 冲突描述 | 处理 |
|---|----------|------|
| — | 无 | |

---

## 9. 签字

| 角色 | 姓名 | 日期 | 结论 |
|------|------|------|------|
| 架构师/研发负责人 | | | |
| 后端负责人 | | | |
| 算法/边缘负责人 | | | |
| DevOps | | | |
| PMO | | | |

---

## 10. 会后动作（48h）

| # | 动作 | 文档 |
|---|------|------|
| 1 | 结论写入 architecture_changelog（待建）或 design_dev 版本记录 | |
| 2 | 更新 architecture_design_index §5 DoD | |
| 3 | 修订项同步 sprint_task_backlog §6.1 | |
| 4 | gap 清单状态更新 | poc_to_production_gap.md |
| 5 | 若 API/DB 变更：补充 OpenAPI 或 ADR 短页 | |

---

**建议议程时间**：6/18（周四）09:00-11:30，紧接 PM-401 结论消化。
