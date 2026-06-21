# 架构决策记录（ADR）

**Architecture Decision Records · Phase 1**

| 项目 | 内容 |
|------|------|
| 版本 | V1.3 |
| 更新 | 2026-06-21 |

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
| 状态 | **已采纳**（2026-06-18 PK 收敛口径） |
| 背景 | PoC 需零依赖启动；试点需重启不丢 |
| 决策 | dev/demo：`HOTPOT_DATABASE_URL` 未设置 → SQLite。**staging / 试点 / UAT / Go-Live：必须设 `HOTPOT_DATABASE_URL` 走 PostgreSQL profile**，并纳入启动冒烟门禁（无则拒绝上线）。不强制本地默认 PG。 |
| 后果 | docker `--profile postgres`；两店共库 tenant 隔离；试点部署清单须含 PG+env+health+backup 一键 profile（Codex 反提采纳） |
| 代码 | `cloud/event_hub/db.py` factory |

---

## ADR-004：API 路径 — 试点保留无版本前缀，新 API 用 /v1

| 项 | 内容 |
|----|------|
| 状态 | **已采纳**（2026-06-18 已实现） |
| 背景 | design_dev §1.4.4 目标 `/v1`；看板已对接 `/summary` |
| 决策 | 全部 legacy 路径新增 `/v1` 同 handler 别名；旧路径标 `deprecated=True` 并回 `Deprecation: true` 头；`core.js` 已切 `/v1`。`/health` `/metrics` `/auth/token` 不在弃用集。 |
| 后果 | 旧路径过渡期双活；下一 major 移除。共 24 别名 + 中间件。 |
| 文档 | [architecture_api_spec.md](architecture_api_spec.md) |

---

## ADR-005：边缘推理默认 yolo，dev 可用 mock

| 项 | 内容 |
|----|------|
| 状态 | **已采纳** |
| 日期 | 2026-06-17（补充外部参考基准，待本项目验证） |
| 背景 | mock 便于 CI；试点需真实 CV |
| 决策 | 生产 `HOTPOT_DETECTOR_BACKEND=yolo`；CI/培训 `mock` |
| 后果 | DEV-410 切换 + 准确率报告 |
| 参考基准 | 工业 AOI 场景（PCB 焊点/18 类缺陷/0.1mm 级）报告显示 YOLOv8s、VLM-only、YOLO+VLM 融合各有延迟/漏检差异；该数据仅作为外部参考，不等同于餐饮桌态/后厨场景实测。见 ADR-014 |
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
| 状态 | **提议中 → 范围降级**（2026-06-18 PK 收敛） |
| 背景 | 设计原则断网 24h |
| 决策 | 边缘 `edge/queue/` SQLite 缓存 OpsEvent，恢复后 bulk POST Hub |
| 收敛口径 | **24h 断网容灾不作为 Phase 1 Go-Live 硬性验收**：除非 DEV-105 在本期完成最小 edge SQLite 队列 + replay + 压测，否则该能力降级为 **P1.5**。文档/NFR 不得标注为 Phase 1 已兑现。 |
| 后果 | DEV-105 实现与压测（若纳入本期）；否则进入 P1.5 backlog |
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
| 隔离不变量（Phase 1 已启用） | **跨店隔离 enforcement 不延后到 P2**：任何**已认证**的 store-scoped 用户（JWT，`store_id≠*`）读/写他店一律 403，即使在 demo 模式（仅匿名 demo 便利账号 `store_id=*` 放行）。由 `auth.enforce_store_read/write` 强制，`tests/test_store_isolation.py` 固化为回归不变量。 |
| 关联 | [product_hierarchy_national_chain.md](product_hierarchy_national_chain.md) · [architecture_hierarchy_phase_plan.md](architecture_hierarchy_phase_plan.md) |

---

## ADR-010：F-TASK 轻量任务督办引擎

| 项 | 内容 |
|----|------|
| 状态 | **已采纳 / Phase 1.x 内核已实现** |
| 日期 | 2026-06-16 |
| 背景 | SOP 指派、告警 ack、来料异常、翻台督促分散，组织执行缺少统一闭环 |
| 决策 | Phase 1.x 新增 `tasks` + `task_events` 轻量任务内核；`overdue/escalated` 作为 SLA 派生标记，不作为主状态；`sop_assignments` 保持兼容写入路径；当前分支已落地 `/v1/tasks`、`task_store.py`、`task_factory.py`、`dashboard/tasks.html` 与企微督办卡片。 |
| 权限 | `reopen` 仅店长/督导/PMO 且必须 reason；`cancel` 未 closed 前由创建人/店长/督导执行，closed 后仅 admin override；`reassign` 必须写 task_event 和 `sla_policy` |
| SLA | `reassign` 必须显式选择 `reset_from_reassign` 或 `keep_original_due_at`，禁止隐式重置 |
| 后果 | 可替代 DEV-421 并承接后厨损耗行动闭环；不作为 IMP-402 Go-Live 硬门槛；P2 继续补区域 rollup、SLA 调度器接线与配置化。 |
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

## ADR-013：设计先行、实现与真数据接入分期

| 项 | 内容 |
|----|------|
| 状态 | **已采纳** |
| 日期 | 2026-06-16 |
| 背景 | 全国连锁终局（solution.md）与 2 店试点（PRD Phase 1）并存；需避免「文档缩水」或「实现超前无规格」两种漂移 |
| 决策 | **产品与架构按终局写全**（功能族 F-xxx、角色、ER、API、ADR、部署拓扑）；**软件实现**与**硬件/真数据接入**按 Phase 分期落地。三层轨道分离，不得混为一谈 |
| 设计层 | PRD + 层级/任务/追溯详设 + `architecture_*` + ADR；允许规格超前于当前代码 |
| 实现层 | P1 Must Have → P1.5（F-TASK kernel）→ P2（Admin CRUD、strict RBAC）→ P3；新能力默认 **feature flag**，未开启不算上线 |
| 接入层 | mock / file / simulator → 单店真机（RTSP、MQTT、ERP/POS API）→ 多店规模化；打桩组件必须文档化**替换路径** |
| 契约优先 | API、OpsEvent（ADR-002）、`store_id`/`data_scope`（ADR-009）先定契约；实现可返回 stub，UI 可先只读，但须预留扩展位 |
| 打桩规范 | 每个 stub（如 `device_stub`、`iot_stub_bridge`）在架构映射表标明：输入源、输出事件类型、真源替换任务（DEV-xxx） |
| 验收门禁 | Phase 1 仅以 [phase1_mvp_acceptance_checklist.md](phase1_mvp_acceptance_checklist.md) + PRD §12.1 为准；P1.5/P2 能力不得作为 IMP-402 前置，除非书面变更 |
| 后果 | 对外统一口径：「方案是全的，试点是分步的」；评审时区分「设计完整性」与「当前 Phase 实现度」 |
| 关联 | [product_design.md §2 P8](product_design.md#2-产品原则) · [architecture_design_index.md §1.1](architecture_design_index.md#11-设计--实现--接入三轨道) · [architecture_hierarchy_phase_plan.md §7](architecture_hierarchy_phase_plan.md#7-poc--目标态映射) |

### ADR-013 分期矩阵（摘要）

| 能力域 | 设计写全 | 实现 Phase | 真数据 Phase |
|--------|----------|------------|--------------|
| 单店七模块 F-H/T/K/S/C/A/R/P | ✅ | P1 | CV/IoT：mock→真机 |
| 层级 + 驾驶仓 F-HQ06/07、F-EXEC01 | ✅ | P1 只读 v1 | Hub rollup |
| 运营后台 F-HQ08~11 | ✅ | P2 DB + strict | — |
| 任务督办 F-TASK | ✅ | P1.5 kernel | 事件驱动建单 |
| 增收 F-SALES | ✅ | P2 rule-based | 桌态/POS 真信号 |
| 追溯 F-TRACE | ✅ | P2 查询 API | 复用 OpsEvent |

---

## 变更流程

1. 新 ADR 追加本文，状态：提议中 → 已采纳 / 已废弃  
2. AR-401 / Sprint Review 可晋升「提议中」→「已采纳」  
3. 重大变更同步 [architecture_changelog.md](architecture_changelog.md)

---

## ADR-014：YOLO+VLM 三级过滤架构外部基准参考

| 项 | 内容 |
|----|------|
| 状态 | **提议中** |
| 日期 | 2026-06-17 |
| 背景 | hotpot_smart_ops 采用三级过滤（YOLO→sVLM→VLM+LLM），但当前仓库尚未沉淀餐饮桌态/后厨场景的真实数据集、标注集和边缘硬件 benchmark。工业 AOI 项目（PCB 焊点检测，12,000 训练集/3,000 测试集/18 类缺陷/0.1mm 级）可作为工程选型参考，但不可直接外推为本项目验收指标 |
| 决策 | 继续保持 YOLO-first、VLM feature flag 的技术路线：YOLO 负责一级快速筛选（结构化检测），sVLM/VLM 负责二级语义判断，LLM 负责三级综合决策。是否晋升为已采纳，需补齐本项目样本集、Jetson/边缘设备实测、误报/漏报验收阈值 |
| 后果 | 1. 对 hotpot_smart_ops 当前 mock detector 的替换优先级无影响（YOLO 先行，VLM 层配置化） 2. VLM 模块预留 feature flag，默认 off 3. Phase 1 NFR 仍以 `<1s（边缘）` 为验收目标；YOLO-only 与 YOLO+VLM 的细分预算待本项目 benchmark 后再固化 |
| 外部参考基准 | YOLOv8s: mAP 91.2%, 漏检 2.8%, 8ms；VLM-only: 漏检 6.5%, 320ms, 幻觉 4-8%；YOLO+VLM 融合: mAP 93.4%, 漏检 1.2%, 45ms。该组数据为 AOI 场景参考，需补来源与复现实验说明 |
| 关联 | ADR-005 · `docs/architecture_design_phase1.md` §3 六业务闭环 · `edge/detector/hotpot_detector.py` · `cloud/vlm_review/` |


---

## ADR-015：Event Hub 架构治理（组装根 + Runtime DI + 路由边界 + 集中 RBAC）

| 项 | 内容 |
|----|------|
| 状态 | **已采纳**（2026-06-18，补记两轮重构决策） |
| 背景 | 2026-06-17~18 两轮重构（Claude router-split + Codex hardening）显著改变了 Event Hub 结构，但此前无 ADR 记录，违反 development_delivery_plan §2.3「代码路径与 ar401 映射一致」的治理要求。 |
| 决策 | 1) **app.py 为组装根**（composition root）：仅 `runtime.init` + `lifespan` 启停 + `include_router`，不含路由逻辑。2) **单例经 `runtime.py` 容器延迟绑定**（hub/db/alert_gateway/org_registry），路由直接 `runtime.X` 访问；测试经 `runtime.init` 注入，禁止 routers→app 反向依赖。3) **路由按 10 业务域拆 `routers/*.py`**（system/auth/ingest/receiving/sop/iot/reports/alerts/org/admin），每域单一职责。4) **RBAC 集中于 `rbac.py`（RolePolicy）**，auth.py 委托，`test_rbac_policy` 守 backend↔`rbac.json` 对齐。5) **`/v1` 别名 + Deprecation 治理**（ADR-004）：legacy 同 handler 双挂、`deprecated=True`、中间件 `Deprecation` 头，显式 legacy 集合。6) **纯业务逻辑入 `domain/`**（health/turnover），无 FastAPI/状态依赖。 |
| 后果 | app.py 986→170 行（新增安全 profile 门禁后仍保持组装根职责）；可并行开发与独立测试；128 passed；pyflakes 干净。新增路由族须落到对应 `routers/*.py`，新权限改 `rbac.py` 单一源，新决策追加 ADR。 |
| 关联 | ADR-004 · `cloud/event_hub/{app,runtime,rbac}.py` · `routers/` · `domain/` · `docs/superpowers/specs/2026-06-17-event-hub-router-split-design.md` |

---

## ADR-016：Phase 1 创业切入口以后厨损耗预测为 lead loop

| 项 | 内容 |
|----|------|
| 状态 | **已采纳**（2026-06-19） |
| 背景 | 外部创业讨论将产品聚焦到“最痛、最可量化 ROI 的后厨损耗预测”。现有全局设计覆盖翻台、后厨、SOP、成本、告警、日报、层级，但 Phase 1 若五线并进，试点价值叙事会分散。 |
| 决策 | **全局定位不变**：仍是连锁火锅门店运营副驾驶。**Phase 1 市场切入口收束为一条主路径**：ERP/POS/采购单基线 + PDA 收货/称重/签字 + IoT 冷链/门磁 + 成本页归因 + 告警/SOP/日报闭环，先证明后厨损耗 ROI。架构上将 C-05 从“来料成本”升级为“来料成本 / 损耗预测 lead loop”，规划 `/v1/cost/loss-risk`，但 P1A/P1B 先复用现有 receiving、iot、cost snapshot 与 OpsEvent。 |
| 分期 | P1A 损耗可见：短重/超温/质差/金额/责任链；P1B 损耗预测：规则 baseline TopN，必须有 reason；P1C 行动闭环：复称/优先消耗/退货留证/SOP 整改接 `/v1/sop/assign`，后续接 F-TASK；P2 多店对标；P3 订货/备货优化。 |
| 边界 | 只做预测、建议、排序、归因、人工确认；不做自动扣款、自动退货，不用黑盒模型替代厨师长判断。 |
| 后果 | 产品北极星调整为“可归因后厨损耗闭环率”；PRD 新增 F-C06/F-C07；delivery plan 新增 LOSS-401~403；NFR 增加 TopN 可解释性。翻台/SOP/告警/日报不删除，作为损耗闭环支撑场景逐步接入。 |
| 关联 | [kitchen_loss_prediction_wedge_plan.md](kitchen_loss_prediction_wedge_plan.md) · [product_design.md §1.3.1](product_design.md#131-创业切入口phase-1-聚焦) · [architecture_design_phase1.md](architecture_design_phase1.md) C-05 · [development_delivery_plan.md §3.2.1](development_delivery_plan.md#321-后厨损耗预测切入口p1a--p1b--p1c) |

---

## PK 收敛纪要（2026-06-18 · Claude × Codex）

事实漂移修正（ADR-004 已采纳 / ar401 映射 / 角色计数）+ 设计判断收敛：

| 点 | 收敛结论 |
|----|---------|
| A 持久化 | dev/demo SQLite；staging/试点/UAT/Go-Live 必须 PG profile + 冒烟门禁（ADR-003） |
| B 离线 24h | 不作 Phase 1 Go-Live 硬验收；未实现+压测则降 P1.5（ADR-008） |
| C F-TASK | 已从“仅规划/flag”收敛为 **Phase 1.x 已实现内核**：`/v1/tasks`、状态机、任务中心、企微督办卡片已落地；仍非 IMP-402 Go-Live 硬门槛，区域 rollup/SLA 调度接线留 P2。 |
| D NFR | `<1s 桌态` `<200ms P95` 为 **target**；Hub P95 可脚本实测，CV 真链路待 BL-01/DEV-408~410 benchmark |
| E 架构 ADR | 补 **ADR-015**（本文） |

**Codex 反提（已纳入待办）**：① 登录页角色选择应产品化「去权威化」——后端已是权威（`login_user` 角色绑定），登录页下拉仅提示，后续应移除客户端选角色；② strict 跨店隔离不宜等 P2 → **已落实**：已认证用户跨店读/写 403 在 Phase 1（含 demo）即生效，`tests/test_store_isolation.py` 固化（见 ADR-009 隔离不变量）；③ mock/stub/real 须显式标注（已在 test_cases_phase1.md 图例落实）；④ 试点部署一键 profile（PG+env+health+backup）——并入 ADR-003 后果与部署清单。

---

## ADR-017：边缘 AI 硬件分期 Profile（Jetson 开发机 → RK3588 量产）

| 项 | 内容 |
|----|------|
| 状态 | **已采纳**（2026-06-19 · wedge PK 收敛） |
| 背景 | 创业切入需在边缘跑 VLM+LLM；外部讨论给出云 API 原型 → Jetson 全栈验证 → RK3588 量产的硬件分期，需固化为决策并明确 Phase 1 承诺边界 |
| 决策 | 三段硬件 profile：① **原型**：旧安卓/PC + 云 API（通义千问/DeepSeek），仅验证预测逻辑；② **开发机**：Jetson Orin Nano Super 8GB（官方 Super profile：67 INT8 TOPS），跑全栈 `Qwen2.5-VL-3B` + `Qwen2.5-3B-Instruct`（llama.cpp/INT4，VLM+LLM 同驻需 ≥16GB 理想 32GB），用于跑通链路；③ **量产**：RK3588（6 TOPS NPU，RKNN 工具链），YOLO-first 降成本，与 ADR-005/ADR-014 一致 |
| 边界 | **VLM/LLM 本地常驻列为「实验验证」而非 Phase 1 承诺**；Phase 1 边缘检测仍以 YOLO-first（ADR-005）为准，VLM 经 feature flag（ADR-014）；推理延迟目标 ≤3s、盒子稳定性优先于模型"智商" |
| 后果 | `edge/detector`（YOLO/RKNN）与 `edge/rknn_deploy` 复用；新增模型量化与 Jetson 部署脚本为 P1B 实验项；不在硬件 All in，签首付费客户后再批量 |
| 关联 | ADR-005 · ADR-014 · `edge/` · [kitchen_loss_prediction_wedge_plan.md §7.1/§8.6](kitchen_loss_prediction_wedge_plan.md) |

---

## ADR-018：行业模板与边缘 Profile（Industry Template / Edge Profile）

| 项 | 内容 |
|----|------|
| 状态 | **提议中**（2026-06-19 · 先定契约，代码不抢 Phase 1） |
| 背景 | 双线商业化（运营商渠道 + 餐饮产品化）要求把单一火锅多店能力抽象为「行业智能体模板 + 按客户参数实例化」，现有 `store`/`org_registry` 多租户只支撑火锅多门店，不足以承载跨行业模板 |
| 决策 | 定义模板与实例契约（先文档、后实现）：`template_id`、`vertical`（hotpot/园区/机房…）、`config schema`（阈值/特征/推送时段）、`feature_flags`、`OTA package`（模型+规则下发）、`客户实例边界`（tenant ↔ template ↔ store/site）。运营商场景的盒子定位「本地预处理（降带宽/云存储）+ 行业模板」 |
| 边界 | Phase 1 **不实现**模板引擎；仅冻结契约，避免后续返工。多租户隔离不变量（ADR-009）在引入 template/tenant 维度时必须保持 |
| 后果 | 后续 P2+ 新增 `templates/instances` 模型与 OTA 通道；`store scope` 升级为 `tenant × template × site` scope |
| 关联 | ADR-009（data_scope）· ADR-015（治理）· [kitchen_loss_prediction_wedge_plan.md §8.2](kitchen_loss_prediction_wedge_plan.md) |

---

## Wedge PK 收敛纪要（2026-06-19 · Claude × Codex）

针对创业切入融合（DeepSeek 完整会话）的 PK，收敛如下：

| 点 | 收敛结论 | 落地 |
|----|---------|------|
| /v1/cost/loss-risk | **本期落最小只读桩**（不停在文档） | ✅ **LOSS-402 已实现**：`routers/cost.py` + `domain/loss_risk.py` 规则 baseline（TopN risk_score/reason/suggested_action，store-scoped），`tests/test_loss_risk.py` 4 passed |
| daily_scheduler 多时段 | 现为**单时段单任务**；三时段（15:00 备货/22:00 损耗/周一周报）需 **schedule profiles**，非简单改 `HOTPOT_DAILY_REPORT_HOUR` | wedge §7/§8 措辞已修正为「单时段临时演示」 |
| L2 特征工程 | `cost_control/analyzer.py` 仅够 P1A 来料异常；先做 **snapshot/JSON feature_builder + 测试**，暂不建 `loss_features/loss_predictions` 表，pay-test 通过或需跨天回放再落表 | wedge §8.4 已注明 |
| VLM 废料识别 | 现仅 `review/quality-grade/table-clean-ready`；废料识别需新增 `/waste-estimate`；MVP 先用手动 3 按钮+台账，不阻塞 loss-risk | wedge §8.3 已注明 |
| 硬件分期 | 补 **ADR-017**（VLM/LLM 本地常驻为实验，非 P1 承诺） | ✅ 本文 |
| 运营商/模板化 | 补 **ADR-018**（template_id/vertical/config/flags/OTA/实例边界，先定契约） | ✅ 本文 |

**Codex 反提（已落实）**：F-C03 手动打分降级同步至 `phase1_mvp_acceptance_checklist.md` 与 `test_cases_phase1.md`；LOSS-402 已从「下一步」提前实现为只读桩。

---

## ADR-019：后厨损耗预算/预测真实设备接入 Profile

| 项 | 内容 |
|----|------|
| 状态 | **提议中**（2026-06-21 · 试点执行方案） |
| 背景 | `/v1/cost/loss-risk` 已落规则 baseline，但创业主线要证明真实 ROI，必须从 mock/stub 走向真实设备数据。若一次性采购全量硬件（RFID、改刀双秤、全后厨 VLM 摄像头、本地常驻大模型），会抬高现场复杂度和现金压力。 |
| 决策 | 真实设备接入采用 **P1A 最小强证据 Profile**：收货秤 + 探针温度 + 冷藏/冷冻温湿度 + 冷库门磁 + PDA + 1~2 路关键摄像头 + RK3588 边缘盒 + 工业 IoT 网关。协议层统一为 `sensor_id + stage + type + value + unit + ts + raw.protocol` 事件，先进入 snapshot feature builder；pay-test 通过或跨天回放需要时，再落 `loss_features/loss_predictions` 表。 |
| 硬件 | 延续 ADR-017：Jetson Orin Nano Super 8GB 用于 VLM/LLM 开发验证；试点/量产默认 RK3588 16GB 工业边缘盒。工业网关需支持 RS232/RS485、Modbus RTU、标准 MQTT/HTTP；摄像头仅做留证与二期 VLM 输入，不作为 P1A 主证据。 |
| 分期 | P0 数据基线；P1A 真设备收货/冷链接入；P1B 损耗预算/预测 feature snapshot；P1C 风险转任务/SOP/日报闭环；P2 双店复制与模板化。 |
| 边界 | P1A 不采购 RFID 全追溯、全量 VLM 摄像头、改刀双秤；不承诺本地 VLM/LLM 常驻；设备数据作为证据与建议，自动扣款/自动退货仍禁止。 |
| 后果 | 新增方案文档 `kitchen_loss_real_device_solution.md`（SSOT）+ 执行附录 `kitchen_loss_budget_solution.md`（接口契约冻结 + 特征持久化/离线口径细化）；后续任务以 LOSS-501~508 管理。新增 store-scoped 接口契约 `/v1/cost/loss-budget`、`/v1/receiving/quality-tap`、`/v1/vlm/waste-estimate`（字段/降级/验收测试见附录 §2，遵 ADR-009 跨店隔离）。Phase 1 特征持久化到 `store_snapshots(kind="loss_features")`/events，关系表延后 LOSS-508。现场验收从“页面能演示”升级为“真实设备在线率、读数延迟、数据完整率、闭环损耗金额”四类指标。 |
| 关联 | ADR-016 · ADR-017 · ADR-018 · ADR-009（跨店隔离） · [kitchen_loss_real_device_solution.md](kitchen_loss_real_device_solution.md) · [kitchen_loss_budget_solution.md](kitchen_loss_budget_solution.md) · `shared/iot_sensors.py` · `edge/iot_mock/mqtt_bridge.py` · `cloud/event_hub/routers/cost.py` · `cloud/event_hub/db.py`（store_snapshots） |
