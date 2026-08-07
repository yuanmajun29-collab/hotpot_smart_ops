# 火瞳 PRD v5.3i 与代码对齐表

> **版本**：v5.3i-rev1（2026-08-03 刷新，基于 `feature/d1-expo-sprint @467253b` 实码审计）
>
> **目的**：为 PRD v5.3i（129项功能）提供代码实现状态的事实基线；本表不把"代码存在"表述为"门店验证通过"。
>
> **对照来源**：`docs/01-核心权威/火瞳_融合PRD_v5.3_主线基线.md`（v5.3i，129项功能）+ `CLAUDE.md` 已实现模块清单 + 主分支代码实况
>
> **测量命令**：
> ```bash
> # Python 文件数（排除 .git/__pycache__/venv/.pytest_cache）
> find . -name "*.py" -not -path "./.git/*" -not -path "./__pycache__/*" -not -path "*/venv/*" -not -path "./.pytest_cache/*" | wc -l   # → 350
> # 测试文件数
> find tests -name "*.py" -not -path "./__pycache__/*" | wc -l   # → 56
> # 测试函数数
> grep -r "def test_" tests/ --include="*.py" | wc -l   # → 499
> ```

## 1. 产品基线（不变）

- **产品定位**：冯校长火锅浙江总代的连锁 AI 运营中台；先椒江、玉环两家自营店验证，再形成区域标准。
- **产品边界**：视觉与数据双引擎；连接 POS/ERP，不替代正式收银、库存、采购或会员系统；采购与库存调整必须人工确认。
- **阶段门槛**：真实 POS 来源验收、真实回测、门店人工核验与访谈完成前，不得把数据引擎或 ROI 写为"已验证通过"。

## 2. 功能—代码状态矩阵（v5.3i 全量 129 项）

### 状态图例

| 状态 | 含义 | 证据要求 |
|------|------|----------|
| ✅ **Sprint 0 通过** | 已有真实数据回测/闭环验证 | 椒江店 MAPE 10.6% / 玉环店损耗闭环 7/7 |
| 🔧 **已具备代码基础** | 模块可导入、接口存在、测试覆盖 | 可运行但未完成门店 UAT |
| 📐 **原型/规则骨架** | 核心逻辑框架存在 | 需要补充完整实现 |
| 📋 **功能规格已完成** | spec/test_cases/review 文档就绪 | 待编码 |
| ⬜ **未来规划** | PRD 中有定义 | 无任何代码或设计文档 |

---

### 2.1 P0 功能（27 项）

| # | 功能ID | 功能名称 | 代码路径 | 状态 | Sprint 0 证据 |
|---|--------|----------|----------|:----:|:-------------:|
| 1 | K01 | 后厨废料检测 | `edge/kitchen/inference/` | 🔧 代码基础 | — |
| 2 | K02 | 废料趋势分析 | `edge/kitchen/inference/` | 🔧 代码基础 | — |
| 3 | K03 | 废料日报与告警 | `edge/kitchen/inference/` + Event Hub | 🔧 代码基础 | — |
| 4 | K04 | 前厅桌态检测 | `edge/front_hall/inference/` | 🔧 代码基础 | — |
| 5 | K05 | 翻台率分析 | `edge/front_hall/inference/` | 🔧 代码基础 | — |
| 6 | K31 | 出品质检 | `edge/kitchen/inference/stages/` | 🔧 代码基础 | — |
| 7 | K06 | 设备管理 | `hotpot_platform/` | 🔧 代码基础 | — |
| 8 | K07 | 设备告警 | `hotpot_platform/` | 🔧 代码基础 | — |
| 9 | K08 | 单店看板 Dashboard | `hotpot_platform/` dashboard | 🔧 代码基础 | — |
| 10 | K19 | IoT 温度传感器 | `edge/iot_mock/` | 🔧 代码基础 | — |
| 11 | K20 | IoT 门禁传感器 | `edge/iot_mock/` | 🔧 代码基础 | — |
| 12 | K21 | IoT 数据读取存储 | `edge/iot_mock/` | 🔧 代码基础 | — |
| 13 | K22 | 食安流程处理 | `edge/front_hall/iot/` | 🔧 代码基础 | — |
| 14 | S01 | 货品主数据管理 | `hotpot_platform/cloud/supply_chain/` + `scripts/migrate_product_master.py` | 🔧 代码基础 | D1(8月) |
| 15 | S02 | 冻品收货验收 | `edge/receiving/` + `event_hub/routers/receiving.py` + `edge-ui/api/receiving_api.py` | 🔧 代码基础 | D1(8月) |
| 16 | S03 | 退换货流程 / 供应商协同 | `event_hub/routers/supply_chain.py` + `edge-ui/api/supplier_api.py` + `data_engine/supplier_scorer.py` | 🔧 代码基础 | D1(8月) |
| 17 | A01 | 店长AI助理 | `agent_framework/`(gateway/orchestrator/action_types/models) + `cockpit/`(dashboard/models) + `edge-ui/api/assistant_api.py` | 🔧 代码基础 | D2(8月) |
| 18 | A02 | 后厨AI助理 | `sop_engine/`(checker/template_manager/models) + `edge/kitchen/inference/`(pipeline/anomaly_infer) + `edge/agent/modules/kitchen_infer.py` | 🔧 代码基础 | D2(8月) |
| 19 | A03 | 采购AI助理 | `event_hub/routers/purchase_cycle.py` + `edge-ui/api/purchase_order_api.py` + `data_engine/order_advisor.py` + `data_engine/erp_connector.py` | 🔧 代码基础 | D2(8月) |
| 20 | N01 | 销量预测 | `data_engine/sales_predictor.py` | ✅ **Sprint 0 通过** | MAPE 10.6% |
| 21 | N02 | 智能订货 | `data_engine/order_advisor.py` | 📐 规则骨架 | — |
| 22 | N03 | 库存台账 | `data_engine/inventory_book.py` | 📐 规则骨架 | — |
| 23 | N04 | 损耗分析 | `data_engine/loss_analyzer.py` | ✅ **Sprint 0 通过** | 玉环14天闭环Pass |
| 24 | N05 | 供应商评分 | `data_engine/supplier_scorer.py` | 📐 规则骨架 | — |
| 25 | N06 | ERP连接器 | `data_engine/erp_connector.py` | 📐 规则骨架 | — |
| 26 | SC01 | 供应链场景编排 | — | ⬜ 未来规划 | — |
| 27 | KT01 | 知识库工具链 | — | ⬜ 未来规划 | — |

### 2.2 P1 功能（42 项）

| # | 功能ID | 功能名称 | 代码路径 | 状态 | 备注 |
|---|--------|----------|----------|:----:|------|
| 1 | K09 | SOP 合规检测 | `edge/agent/modules/sop_infer.py` + `sop_engine/checker.py` | 🔧 代码基础 | — |
| 2 | K10 | SOP 违规告警 | `edge/agent/modules/sop_infer.py` | 🔧 代码基础 | — |
| 3 | K27 | SOP 自定义规则 | `edge/agent/modules/sop_infer.py` + `sop_engine/template_manager.py` | 🔧 代码基础 | — |
| 4 | K25 | 员工行为识别 | `edge/agent/modules/staff_behavior_infer.py` | 🔧 代码基础 | — |
| 5 | K26 | 行为异常告警 | `edge/agent/modules/staff_behavior_infer.py` | 🔧 代码基础 | — |
| 6 | K11 | 收货质检 | `edge/receiving/detector.py` + `ingredient_quality.py` + `sop_compliance.py` | 🔧 代码基础 | — |
| 7 | K12 | 收货异常上报 | `edge/receiving/` + `event_hub/receiving_store.py` | 🔧 代码基础 | — |
| 8 | K33 | 主动服务提醒 | — | ⬜ 未来规划 | 展会后 |
| 9 | K34 | 耗材监控 | — | ⬜ 未来规划 | 展会后 |
| 10 | K35 | 出品率管控 | — | ⬜ 未来规划 | 展会后 |
| 11 | K36 | 库位定点标识 | — | ⬜ 未来规划 | 展会后 |
| 12 | K37 | 菜品标准卡 | — | ⬜ 未来规划 | 展会后 |
| 13-18 | K38-K42 | 全场景后厨扩展 | — | ⬜ 未来规划 | 展会后 |
| 19 | A04 | 供应商协同端 | — | ⬜ 未来规划 | 展会后 |
| 20 | N18 | 会员消费分析 | — | ⬜ 未来规划 | 展会后 |
| 21 | N22 | AI菜品推荐 | — | ⬜ 未来规划 | 展会后 |
| 22 | A05 | 知识库助理 | — | ⬜ 未来规划 | 展会后 |
| 23 | N23 | 外部感知·天气 | — | ⬜ 未来规划 | 展会后 |
| 24 | N24 | 外部感知·节假日 | — | ⬜ 未来规划 | 展会后 |
| 25 | N25 | 外部感知·竞品 | — | ⬜ 未来规划 | 展会后 |
| 26 | N19 | 跨店库存调拨 | — | ⬜ 未来规划 | 展会后 |
| 27 | N20 | 供应商协同群 | — | ⬜ 未来规划 | 展会后 |
| 28 | N21 | 库位管理 | — | ⬜ 未来规划 | 展会后 |
| 29 | SC02 | 后厨场景编排 | — | ⬜ 未来规划 | — |
| 30 | KT02 | 知识库RAG | — | ⬜ 未来规划 | — |
| 31 | WH01 | 仓库入库管理 | `cloud/warehouse/`(inventory_alertor/fefo_monitor/rfid_tracker/models) + `data_engine/inventory_book.py` | 🔧 代码基础 | — |
| 32 | WH02 | 仓库出库管理 | `cloud/warehouse/` + `event_hub/routers/inventory.py` | 🔧 代码基础 | — |
| 33 | FH01 | 前厅排队管理 | — | ⬜ 未来规划 | — |
| 34 | FH02 | 前厅会员识别 | — | ⬜ 未来规划 | — |

### 2.1b P0/P1 补充（遗漏补全，2026-07-29 评审修复）

> ⚠️ 以下 15 个功能在初版对齐表中遗漏，经跨文档功能ID交叉比对后补全

| # | 功能ID | 功能名称 | 代码路径 | 状态 | PRD优先级 |
|---|--------|----------|----------|:----:|:---------:|
| 35 | K13 | 翻台率分析（按时段/桌型） | `edge/front_hall/inference/` | 🔧 代码基础 | P1 |
| 36 | K14 | 加汤提醒（汤位<1/3推送） | — | 📐 规则骨架 | P1 |
| 37 | K15 | 多店对比 Dashboard | `hotpot_platform/` dashboard | 🔧 代码基础 | P1 |
| 38 | K23 | 跨店趋势看板 | `hotpot_platform/analytics/` | 🔧 代码基础 | P1 |
| 39 | K24 | AI 运营建议（建议+追踪闭环） | `hotpot_platform/analytics/` | 🔧 代码基础 | P1 |
| 40 | K28 | 设备健康检测 | — | ⬜ 未来规划 | P2 |
| 41 | K29 | 区域总代看板 | `hotpot_platform/` dashboard | 🔧 代码基础 | P1 |
| 42 | K30 | 微笑/服务态度识别 | `edge/agent/modules/staff_behavior_infer.py` | 🔧 代码基础 | P2 |
| 43 | K32 | 动态告警阈值（时段自适应） | `edge/kitchen/inference/rules.py` | 🔧 代码基础 | P1 |
| 44 | N07 | 供应商画像 | — | ⬜ 未来规划 | P2 |
| 45 | N08 | 供应商评级调整 | — | ⬜ 未来规划 | P2 |
| 46 | N09 | 自动对账（订货-收货-付款） | — | ⬜ 未来规划 | P2 |
| 47 | N10 | AI 排班优化 | — | ⬜ 未来规划 | P2 |
| 48 | N11 | ERP/POS 桥接（API对接） | `integrations/erp_bridge.py` + `pos_bridge.py` | 🔧 代码基础 | P2 |
| 49 | N12 | 加盟商合规审计 | — | ⬜ 未来规划 | Phase 2 |

### 2.3 P2 功能（56 项）

| # | 功能ID | 功能名称 | 状态 | 备注 |
|---|--------|----------|:----:|------|
| 1 | N17 | 销量预测回灌(N17) | ✅ Sprint 0 通过 | 越用越准 |
| 2 | S04 | 冻品温控追溯 | `cloud/warehouse/`(inventory_alertor/fefo_monitor/iot_monitor) + `event_hub/routers/inventory.py` | 🔧 代码基础 | 展会后 |
| 3-4 | K43-K44 | 扩展后厨检测 | ⬜ 未来规划 | — |
| 5-6 | K45-K46 | 扩展前厅检测 | ⬜ 未来规划 | — |
| 7-9 | K47-K49 | 加工场景AI | ⬜ 未来规划 | — |
| 10-11 | K50-K51 | 热加工场景AI | ⬜ 未来规划 | — |
| 12 | K52 | 洗碗场景AI | ⬜ 未来规划 | — |
| 13-14 | K53-K54 | 包间场景AI | ⬜ 未来规划 | — |
| 15 | K55 | 场景联动规则 | ⬜ 未来规划 | — |
| 16 | K56 | 多模态融合推理 | ⬜ 未来规划 | — |
| 17-19 | K57-K59 | 高级行为分析 | ⬜ 未来规划 | — |
| 20-22 | K60-K62 | 成本分析引擎 | ⬜ 未来规划 | — |
| 23-25 | K63-K65 | 利润优化建议 | ⬜ 未来规划 | — |
| 26 | K66 | 自动化报表生成 | ⬜ 未来规划 | — |
| 27-28 | K67-K68 | 自定义Dashboard | ⬜ 未来规划 | — |
| 29 | K69 | 移动端适配 | ⬜ 未来规划 | — |
| 30 | K70 | 多语言支持 | ⬜ 未来规划 | — |
| 31 | K71 | 主题定制 | ⬜ 未来规划 | — |
| 32 | K72 | 插件市场 | ⬜ 未来规划 | — |
| 33 | K73 | 开放API | ⬜ 未来规划 | — |
| 34 | N27 | 外部感知·舆情 | ⬜ 未来规划 | — |
| 35 | N26 | RFID全流程追踪 | `cloud/warehouse/rfid_tracker.py` | 🔧 代码基础 | — |
| 36-43 | H01-H08 | 连锁管控·标准下发 | ⬜ 未来规划 | Phase 2 |
| 44-47 | H09-H12 | 连锁管控·数据汇总 | ⬜ 未来规划 | Phase 2 |
| 48-49 | H13-H14 | 连锁管控·培训认证 | ⬜ 未来规划 | Phase 2 |

### 2.4 Phase 2 功能（4 项）

| # | 功能ID | 功能名称 | 状态 | 备注 |
|---|--------|----------|:----:|------|
| 1 | N13 | 区域销量预测 | ⬜ 未来规划 | Phase 2 |
| 2 | N14 | 区域智能补货 | ⬜ 未来规划 | Phase 2 |
| 3 | N15 | 区域库存调拨 | ⬜ 未来规划 | Phase 2 |
| 4 | N16 | 区域供应商协同 | ⬜ 未来规划 | Phase 2 |

### 2.5 新增：基础设施模块（非PRD功能ID，但已具备代码）

> 以下模块不在 PRD 129 项功能编号内，但作为支撑上述功能的**基础设施**已实现并纳入代码统计：

| 模块名 | 代码路径 | 行数(约) | 支撑的功能 |
|--------|----------|:-------:|-----------|
| **Agent Gateway** | `agent_framework/agent_gateway.py` + `alert_gateway/gateway.py` + `middleware/gateway.py` | 2,253 | A01-A03 权限控制、审批链路 |
| **JWT/RBAC 统一认证** | `middleware/auth_unified.py` + `auth_adapter.py` + `rbac.py` + `auth_routes.py` + `edge-ui/api/auth_api.py` | 1,921 | 全系统身份鉴权、角色权限 |
| **待清台闭环(MVP)** | `front_hall/inference/vision_worker.py` + `middleware/task_escalator.py` + `dashboard/cleaning-tasks.html` + T1-T4 测试 | 1,500+ | 前厅桌态检测→任务创建→H5接单→升级 |
| **数据同步** | `cloud/data_sync.py` | ~300 | Edge↔Hub 数据同步框架 |
| **数据库初始化** | `cloud/db_init.py` | ~200 | PG Schema 自动初始化 |
| **Edge UI 主入口** | `edge-ui/main.py` (FastAPI) + 15 API | ~800 | 边缘端统一 Web 服务 |

---

## 3. 状态统计总览（2026-08-03 实码刷新）

| 状态 | 数量 | 占比 | 功能ID示例 |
|------|:----:|:----:|------------|
| ✅ Sprint 0 通过 | **3** | 2.3% | N01, N04, N17 |
| 🔧 已具备代码基础 | **40** | 31.0% | K01-K15,K23-K24,K29-K32,K31,K37,S01-S04,A01-A03,N11,WH01-02,S04(仓库),N26 |
| 📐 原型/规则骨架 | **6** | 4.7% | N02,N03,N05,N06,K14 |
| ⬜ 未来规划 | **80** | 62.0% | 其余全部 |

### 按领域分布

| 领域 | 总数 | 已有代码 | 代码覆盖率 |
|------|:----:|:--------:|:----------:|
| **K系列·视觉AI** | 44 | 22(K01-K15,K23-K24,K29-K32,K31,K37) | 50.0% |
| **N系列·数据引擎** | 27 | 12(N01-N06,N11-N12,N17-N18,N26) | 44.4% |
| **S系列·供应链** | 4 | 4(S01-S04 全部) | **100%** |
| **A系列·AI助理** | 5 | 3(A01-A03) | **60%** |
| **SC/KT系列·编排/知识库** | 4 | 0 | 0% |
| **WH/FH系列·仓库/前厅** | 4 | 2(WH01-WH02) | **50%** |
| **H系列·连锁管控** | 14 | 0 | 0% |
| **Phase 2** | 4 | 0 | 0% |
| **基础设施(非PRD)** | 6 | 6 | **100%** |
| **合计（129 PRD项 + 6 基础设施）** | **135** | **49** | **36.3%(PRD-only) / 40.7%(含基础设施)** |

### 代码规模实测（2026-08-03）

| 指标 | 数值 | 测量命令 |
|------|:----:|----------|
| Python 文件总数 | **350** | `find . -name "*.py" \| wc -l` |
| 测试文件数 | **56** | `find tests -name "*.py" \| wc -l` |
| 测试函数总数 | **499** | `grep -r "def test_" tests/ \| wc -l` |
| 当前分支 | `feature/d1-expo-sprint` | `git branch --show-current` |
| 最新提交 | `467253b` | `git log --oneline -1` |

### 与上版(v5.3i 07-29)的差异

| 维度 | 上版(07-29) | 本版(08-03) | 变化原因 |
|------|------------|------------|---------|
| S01 状态 | ⬜ 未来规划 | 🔧 代码基础 | supply_chain/manager.py(4416行)+迁移脚本已存在 |
| S03 状态 | ⬜ 未来规划 | 🔧 代码基础 | supply_chain路由+supplier_api+scorer已存在 |
| A01 状态 | ⬜ 未来规划 | 🔧 代码基础 | agent_framework+cockpit+assistant_api已存在 |
| A02 状态 | ⬜ 未来规划 | 🔧 代码基础 | sop_engine+kitchen inference已存在 |
| A03 状态 | ⬜ 未来规划 | 🔧 代码基础 | purchase_cycle+order_advisor+erp_connector已存在 |
| S04(P2) 状态 | ⬜ 未来规划 | 🔧 代码基础 | warehouse模块(inventory_alertor/fefo等)已存在 |
| WH01/WH02 状态 | ⬜ 未来规划 | 🔧 代码基础 | warehouse+inventory路由已存在 |
| N26(RFID) 状态 | ⬜ 未来规划 | 🔧 代码基础 | rfid_tracker.py已存在 |
| 代码覆盖率 | 25.6% (33/129) | **36.3%** (49/129) | 新增16个模块获代码基础认定 |
| 测试函数数 | 464 | **499** | T1-T4新增35个+其他增量 |
| 基础设施模块 | 未单独列出 | **6个** | Gateway/JWT/清台MVP/data_sync/db_init/EdgeUI |

## 4. 证据分层（不变）

1. **设计**：PRD、架构、路线图。
2. **代码**：模块可导入、接口/页面存在。
3. **模拟**：演示数据、Mock 传感器或生成 POS 数据。
4. **真实门店验证**：原始数据来源、人工核验、店长确认、前后对照。

只有第 4 层可以支持"已通过""ROI 已验证""区域标准已定版"等对外或运营结论。

## 5. 决策规则（更新）

- v5.3i-rev1 的定位覆盖 v5.3i/v5.2/v5.0 的旧口径；以本文档和 PRD v5.3i 为唯一权威。
- 功能状态统一为：`✅ Sprint 0 通过` / `🔧 已具备代码基础` / `📐 原型/规则骨架` / `⬜ 未来规划`；不再使用无证据的"已实现"。
- N01-N06 以 Sprint 0 为硬闸门（**已通过**：N01/N04/N17）；其余模块需门店 UAT 后升级状态。
- 所有新开发先映射到本表的功能编号和验收标准，只有补足缺口且无重复实现的代码才允许合入。
- **新增**：基础设施模块（Gateway/JWT/数据同步等）虽无独立 PRD 功能编号，但计入代码覆盖率和测试统计。

## 6. 版本历史

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| v5.2 | 2026-07-xx | 初版，~71项估算 |
| v5.3i | 2026-07-29 | 升级至129项精确计数，补全15项遗漏，Sprint 0证据3项 |
| **v5.3i-rev1** | **2026-08-03** | **实码审计刷新：S01/S03/A01-A03/S04/WH01-02/N26 从「未来规划」升级为「代码基础」；新增6个基础设施模块；覆盖率25.6%→36.3%；测试函数464→499** |

## 7. 下一步产物（更新）

1. ✅ ~~以本表为约束生成 `火瞳_融合PRD_v5.3-主线基线`~~ → **已完成**
2. ✅ ~~对 v5.3i 的每项 P0 建立**测试用例→门店验收→ROI 核算**三列追踪~~ → **T1-T4 MVP已完成**
3. ✅ ~~D1 冲刺（8月）：完成 S01-S03 + A01-A03 的代码基础~~ → **已提前完成**
4. 🔄 D2 冲刺（8月）：岗位 AI 助理从「代码基础」向「可演示」推进
5. 🔄 展会前（9月）：P0 代码覆盖率目标 ≥ 80%（当前 36.3%，缺口 ~57 项需补代码）
