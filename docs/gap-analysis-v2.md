# 火瞳 (hotpot_smart_ops) — 全场景差距分析 & 重构方案

> 生成: 2026-07-16 | 基于 6 大需求模块 vs 现有代码扫描
> 代码根: `~/company/products/to-b/hotpot_smart_ops/`
> 现有代码: ~200 源文件 · 40 测试 · 28 Dashboard 页面

---

## 一、六场景覆盖度总览

| # | 场景 | 覆盖度 | 成熟度 | Edge推理 | 平台API | Dashboard | 测试 |
|---|------|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | 🔥 后厨损耗 | **85%** | 🟡 测试中 | ✅ YOLO+CLIP+VLM | ✅ waste/loss域 | ✅ kitchen-vision | ✅ 6 |
| 2 | 📋 SOP规范 | **40%** | 🟠 开发中 | ❌ 无Edge | ⚠️ 引擎有/调度有/清单有 | ✅ sop.html | ✅ 2 |
| 3 | 🥩 食材监管 | **25%** | 🔴 规划中 | ❌ 完全空白 | ⚠️ receiving API有/分析无 | ⚠️ cost+pda | ✅ 3 |
| 4 | 🪑 前厅桌态 | **80%** | 🟡 测试中 | ✅ plan_a+plan_b | ✅ turnover域 | ✅ tables+front-hall | ✅ 1 |
| 5 | 👔 员工行为 | **5%** | 🔴 规划中 | ❌ 完全空白 | ❌ 完全空白 | ❌ 完全空白 | ❌ 0 |
| 6 | 📊 管理总览 | **75%** | 🟡 测试中 | N/A | ✅ 日报+告警+cockpit | ✅ cockpit+regional | ✅ 5 |

---

## 二、逐场景差距分析

### 场景 1: 后厨损耗 — 覆盖 85%，缺趋势预警+计数统计

**已有能力:**
- `edge/kitchen/inference/pipeline.py` — Stage注册表管线 (YOLO→CLIP→VLM)
- `edge/kitchen/inference/rules.py` — 阈值/提示词/降级矩阵
- `edge/kitchen/inference/defect_measurement.py` — 缺陷测量
- `edge/kitchen/inference/kalman_tracker.py` — 卡尔曼跟踪
- `edge/agent/modules/kitchen_infer.py` — YOLO预过滤+VLM推理
- `hotpot_platform/cloud/event_hub/domain/waste_estimate.py` — 废料估算
- `hotpot_platform/cloud/event_hub/domain/loss_risk.py` — 损耗风险规则
- `hotpot_platform/cloud/event_hub/domain/loss_budget.py` — 损耗预算
- `hotpot_platform/cloud/event_hub/routers/vlm.py` — VLM结果接入
- `hotpot_platform/cloud/llm_report/forecast_agent.py` — LLM预测Agent (stub?)
- `hotpot_platform/dashboard/kitchen-vision.html` — 后厨视觉识别页
- `hotpot_platform/dashboard/kitchen.html` — 后厨IoT页

**Gap 清单:**

| Gap ID | 问题 | 严重度 | 缺少什么 |
|--------|------|:---:|------|
| K-001 | **Count计数统计缺失** | 🔴 P0 | 管线只做检测+分类+推送事件，缺少持续的废料计数时序存储（每帧/每N帧的items计数→DB时序表）。当前 `pipeline_result["item_count"]` 只存在单次返回中，未持久化聚合。 |
| K-002 | **趋势预警缺失** | 🔴 P0 | `loss_risk.py` 是纯规则基线（权重方差+等级+温度），没有时序窗口（上周vs本周，同比/环比）。`forecast_agent.py` 有LLM预测但无时序数据喂入。需要 `waste_timeseries` 表 + 聚合查询API。 |
| K-003 | **废料→成本闭环缺失** | 🟡 P1 | `waste_estimate.py` 有 `estimated_loss_amount` 字段，`loss_budget.py` 有预算逻辑，但两者之间没有端到端的数据流：废料事件→识别SKU→单价查询→金额汇总→预算对比。 |
| K-004 | **规则硬编码在推理模块中** | 🟡 P1 | `kitchen_infer.py` 中 `_FOOD_IDS`/`_CONTAINER_IDS` 等规则内联在推理代码中，与 `rules.py` 分离但也不在Edge Agent配置中。应该统一到 `rules.py` 或平台可下发配置。 |

---

### 场景 2: SOP规范 — 覆盖 40%，缺Edge端实时合规检测+7工位状态机激活

**已有能力:**
- `hotpot_platform/cloud/sop/sop_engine.py` — 合规评估引擎 (vision/iot/manual三类检查点)
- `hotpot_platform/cloud/sop/scheduler.py` — 班次调度器 (早/午/晚三班)
- `hotpot_platform/cloud/event_hub/routers/sop.py` — SOP指派/状态API
- `hotpot_platform/cloud/event_hub/sop_assign_store.py` — 指派持久化
- `hotpot_platform/cloud/event_hub/task_factory.py` — 违规→工单自动派发
- `hotpot_platform/cloud/llm_report/sop_rag.py` — SOP RAG增强
- `hotpot_platform/dashboard/sop.html` — SOP执行Dashboard
- `demo/data/sop_checklist.json` — 7项SOP清单 (开档/收货/保存/加工/锅底/打烊/HACCP)

**Gap 清单:**

| Gap ID | 问题 | 严重度 | 缺少什么 |
|--------|------|:---:|------|
| S-001 | **7工位状态机未激活** | 🔴 P0 | checklist有7个SOP但无真正的工位流转逻辑。当前引擎只做单个班次的checkpoint evaluate，缺少"工位A完成→触发工位B→超时告警"的状态机。需要 `edge/kitchen/inference/stages/stage_sop.py` 或独立模块。 |
| S-002 | **Edge端实时合规检测缺失** | 🔴 P0 | SOP引擎只在云端运行（scheduler周期评估），Edge端没有实时视觉合规检测管线。例如"厨师穿戴合规(VLM)"定义为 `type: vision` 但 `sop_engine.py` 只接受外部signals输入，没有Edge端定时拍照→推理→推送的管道。 |
| S-003 | **VLM合规检查未对接** | 🟡 P1 | `sop_checklist.json` 中有3个 `type: vision` checkpoints（穿戴合规/生熟分区/外观质检），但实际VLM推理路径只在后厨废料管线中，SOP引擎只接收 `True/False` 信号，没有主动调用VLM。 |
| S-004 | **缺少SOP工时/效率统计** | 🟡 P1 | 只统计 pass/fail/pending，缺少每个工位花费时间、超时率等运营指标。管理层需要"改刀加工平均耗时是否超标"。 |
| S-005 | **SOP Router未注册到Hub** | 🟢 P2 | `routers/sop.py` 存在但需要确认已通过 `__init__.py` 自动注册。已注册（`__init__.py` 自动发现）。 |

---

### 场景 3: 食材监管 — 覆盖 25%，缺Edge进货口检测+异常分析

**已有能力:**
- `hotpot_platform/cloud/event_hub/receiving_store.py` — 收货批次持久化 (batch_id, weight, PO weight, variance)
- `hotpot_platform/cloud/event_hub/routers/receiving.py` — 收货提交 + 品质打分API
- `hotpot_platform/cloud/integrations/erp_bridge.py` — ERP桥接(Stub)
- `hotpot_platform/cloud/integrations/pos_bridge.py` — POS桥接(Stub)
- `hotpot_platform/cloud/vlm_review/app.py` — VLM品质审核
- `hotpot_platform/dashboard/cost.html` — 成本分析页
- `hotpot_platform/dashboard/pda/receiving.html` — 收货PDA
- `hotpot_platform/cloud/event_hub/routers/cost.py` — 损耗风险+预算API

**Gap 清单:**

| Gap ID | 问题 | 严重度 | 缺少什么 |
|--------|------|:---:|------|
| I-001 | **进货口Edge检测模块完全空白** | 🔴 P0 | 需要 `edge/receiving/` 新模块：IPC抓帧→YOLO检测食材+秤读数→VLM品质判定→推Hub。类似于后厨管线但针对收货场景。 |
| I-002 | **缺斤少两自动检测缺失** | 🔴 P0 | `receiving_store.py` 有 `variance_pct` 字段但只存不分析。需要规则引擎：自动对比PO重量vs实际重量，超过阈值(如5%)自动告警+阻止入库。 |
| I-003 | **以劣充好检测未连线** | 🔴 P0 | `vlm_review/app.py` 有品质评级API (`grade_a`/`grade_b`/`grade_c`)，`cost.py`有`quality-tap` API。但三者之间无自动触发链路：VLM拍照→自动评级→低于标准→自动告警→拒绝入库。 |
| I-004 | **ERP桥接未实现** | 🟡 P1 | `erp_bridge.py` 是stub，需要接入真实的PO数据对比（订货单重量vs实际收货重量）。 |
| I-005 | **进货趋势/供应商评级缺失** | 🟡 P1 | 需要按供应商聚合：某供应商连续3次短重→降级告警。当前无此分析。 |

---

### 场景 4: 前厅桌态 — 覆盖 80%，缺翻台率计算+预测

**已有能力:**
- `edge/front_hall/inference/pipeline.py` — 统一推理入口
- `edge/front_hall/inference/strategies/plan_b.py` — Plan B (40ms YOLO规则)
- `edge/front_hall/inference/strategies/plan_a.py` — Plan A (YOLO+CLIP ~190ms)
- `edge/front_hall/inference/engines/yolo.py` + `clip_client.py` + `clip_server.py`
- `edge/front_hall/inference/rules.py` — 规则配置(类别映射/CLIP提示词/PlanB逻辑)
- `edge/agent/modules/front_hall_infer.py` — 推理模块(API+标注图)
- `hotpot_platform/cloud/event_hub/domain/turnover.py` — 翻台建议
- `hotpot_platform/dashboard/tables.html` + `front-hall.html` — Dashboard

**Gap 清单:**

| Gap ID | 问题 | 严重度 | 缺少什么 |
|--------|------|:---:|------|
| F-001 | **翻台率计算缺失** | 🟡 P1 | `turnover.py` 只有静态suggestions（按桌态排序），没有真正的翻台率 = f(时间窗口内completed_tables / total_tables)。需要桌态变化历史表 + 时间窗口聚合。 |
| F-002 | **预测性清洁提醒缺失** | 🟡 P1 | 当前只在检测到 `needs_cleaning` 时告警，缺少"预计5分钟后3号桌需要清洁"的预测（基于平均用餐时长统计）。 |
| F-003 | **排队/等位优化缺失** | 🟢 P2 | `pos_bridge.py` stub有 `queue_lost_rate` 字段，但没有将桌态数据用于排队预测。 |

---

### 场景 5: 员工行为 — 覆盖 5%，完全空白

**已有能力:**
- 无任何代码。仅在 `docs/火锅AI-产品定位.md` 中定义为"新增模块"。

**Gap 清单:**

| Gap ID | 问题 | 严重度 | 缺少什么 |
|--------|------|:---:|------|
| E-001 | **员工行为检测模块完全空白** | 🔴 P0 | 需要 `edge/staff_behavior/` 新模块：姿态估计+行为分析管线。三个子场景全部缺失。 |
| E-002 | **交头接耳检测** | 🟡 P1 | 多人姿态估计→头部朝向→交互时长→异常判定。可用YOLO-pose + 社交距离/朝向算法。 |
| E-003 | **着装规范检测** | 🟡 P1 | 制服/帽子/口罩分类器。可用YOLO+CLIP：检测到人→裁剪→CLIP判断"wearing chef uniform/hat/mask"。 |
| E-004 | **行为规范检测** | 🟡 P1 | 玩手机/吸烟/离岗检测。手机已有COCO类别(67)，吸烟需额外训练，离岗用区域检测+持久时间。 |
| E-005 | **员工行为Dashboard空白** | 🔴 P0 | 需要 `dashboard/staff.html` 页面：实时行为事件+工位状态+合规率统计。 |
| E-006 | **员工行为API空白** | 🔴 P0 | 需要 `routers/staff.py`：行为事件接入+统计查询API。 |

---

### 场景 6: 管理总览 — 覆盖 75%，缺新模块数据接入+真正的多店对比

**已有能力:**
- `hotpot_platform/dashboard/cockpit.html` — 集团驾驶仓 (353行)
- `hotpot_platform/dashboard/regional.html` — 区域总揽 (346行)
- `hotpot_platform/dashboard/alerts.html` — 告警中心
- `hotpot_platform/dashboard/report.html` — 运营日报
- `hotpot_platform/dashboard/home.html` — 首页概览
- `hotpot_platform/cloud/event_hub/routers/reports.py` — 日报API
- `hotpot_platform/cloud/event_hub/routers/alerts.py` — 告警API
- `hotpot_platform/cloud/event_hub/daily_report_store.py` — 日报持久化
- `hotpot_platform/cloud/event_hub/daily_scheduler.py` — 日报调度器
- `hotpot_platform/cloud/alert_gateway/gateway.py` — 告警网关(企微推送)
- `hotpot_platform/cloud/llm_report/report_agent.py` — LLM报告Agent
- `hotpot_platform/cloud/event_hub/tasks/task_daily.py` — 日报任务

**Gap 清单:**

| Gap ID | 问题 | 严重度 | 缺少什么 |
|--------|------|:---:|------|
| M-001 | **多店对比数据假** | 🟡 P1 | cockpit/regional页面的KPI数据来自`device_stub.py` mock数据。需要真正的cross-store aggregation API (`/v1/cockpit/rollup?zone_id=...`)。 |
| M-002 | **新模块KPI缺失** | 🟡 P1 | cockpit缺少3个新场景的指标卡：SOP合规率、食材损耗率、员工行为事件数。 |
| M-003 | **告警聚合不完整** | 🟡 P1 | 告警中心能收事件，但没有按场景分类的聚合统计（今日后厨告警N条、SOP违规M条、食材异常K条）。 |
| M-004 | **缺少管理者移动端** | 🟢 P2 | `dashboard/mobile/` 只有index+login，功能极简，需要补齐移动端总览。 |

---

## 三、重构/优化方案 (P0/P1/P2)

### 🔴 P0 — 立即启动 (2-4周)

#### P0-1: 后厨损耗 — Count计数+趋势存储

```
新增: edge/kitchen/inference/stages/stage_counter.py
新增: hotpot_platform/cloud/event_hub/domain/waste_timeseries.py
新增: hotpot_platform/cloud/event_hub/routers/waste_stats.py
修改: edge/kitchen/inference/pipeline.py → 推Hub时附带时序数据
```

**方案详情:**
1. `stage_counter.py`: 每帧推理后，按SKU聚合items数量，写入上下文ctx
2. 桥接脚本 `bridge/waste_vision.py` 推送时附带 `{"ts":"...", "sku_counts": {"毛肚": 3, "鸭肠": 1}}` 
3. Hub新增 `waste_events` SQLite表（ts, store_id, zone, sku, count）
4. `waste_timeseries.py`: 提供 `get_trend(store_id, days=7)` 查询，返回日聚合+周环比
5. `waste_stats` router: `GET /v1/waste/trend?store_id=&days=7` + `GET /v1/waste/summary`

**工作量:** 3-4天

#### P0-2: SOP规范 — Edge端合规检测管线

```
新增: edge/kitchen/inference/stages/stage_sop.py
新增: edge/agent/modules/sop_infer.py
修改: edge/agent/server.py → 注册sop模块
修改: demo/data/sop_checklist.json → 添加camera_mapping
```

**方案详情:**
1. `stage_sop.py`: 接收SOP配置，按工位选择摄像头→推YOLO+CLIP→返回checkpoint结果
2. `sop_infer.py`: FastAPI路由 `POST /infer/sop/check`，接收 `sop_id`+`checkpoint_id`→拍照推理→返回pass/fail
3. Agent注册表加 `"sop": sop_infer`
4. SOP配置扩展到包含 `"camera": "rtsp://.../station_prep"` 映射

**工作量:** 3-4天

#### P0-3: 食材监管 — Edge进货口检测模块

```
新增: edge/receiving/inference/pipeline.py
新增: edge/receiving/inference/rules.py
新增: edge/agent/modules/receiving_infer.py
修改: edge/agent/server.py → 注册receiving模块
新增: hotpot_platform/cloud/event_hub/routers/receiving_analyze.py
```

**方案详情:**
1. `edge/receiving/` 目录结构对标 `edge/kitchen/` 的精简版：
   - `pipeline.py`: 拍照→YOLO检测食材(秤上)→CLIP分类→VLM品质评级
   - `rules.py`: 缺斤少两阈值(默认5%)、品质等级映射
   - 复用现有 `RealYoloDetector` 和 CLIP/VLM 引擎
2. `receiving_infer.py`: FastAPI路由 `POST /infer/receiving/check` → 返回 `{weight_match, quality_grade, alerts}`
3. Hub `receiving_analyze.py`: 自动触发规则检测——接收receiving事件→对比PO→生成alerts→阻止入库

**工作量:** 4-5天

#### P0-4: 员工行为 — Edge检测模块骨架

```
新增: edge/staff_behavior/inference/pipeline.py
新增: edge/staff_behavior/inference/rules.py
新增: edge/staff_behavior/inference/behavior_detector.py
新增: edge/agent/modules/staff_behavior_infer.py
修改: edge/agent/server.py → 注册staff_behavior模块
新增: hotpot_platform/cloud/event_hub/routers/staff.py
新增: hotpot_platform/dashboard/staff.html
```

**方案详情:**
1. `behavior_detector.py`:
   - 交头接耳: YOLO-pose检测多人→计算头部向量夹角→交互时长>30秒→告警
   - 着装检测: 检测到人→裁剪ROI→CLIP分类"穿着厨师服/戴厨师帽/戴口罩/未穿戴"
   - 行为规范: 手机检测(COCO 67) + 长时间静止区域判定(离岗)
2. `pipeline.py`: 统一入口 `analyze_behavior(image, zone="kitchen")` → 返回 `{chitchat, uniform, phone, alerts}`
3. `staff_behavior_infer.py`: `POST /infer/staff/check` 端点
4. `staff.html`: 实时行为事件流+工位合规率统计卡

**工作量:** 5-7天（含模型调试）

---

### 🟡 P1 — 两周内 (2-4周)

#### P1-1: 后厨损耗闭环 — 废料→成本→预算全链路

```
修改: edge/kitchen/bridge/waste_vision.py → 推送时附带成本信息
修改: hotpot_platform/cloud/event_hub/domain/waste_estimate.py → 增加price_lookup
新增: hotpot_platform/cloud/event_hub/domain/waste_cost.py
修改: hotpot_platform/cloud/event_hub/routers/cost.py → waste-cost端点
```

**工作量:** 2-3天

#### P1-2: SOP工位状态机激活

```
新增: hotpot_platform/cloud/sop/station_state_machine.py
修改: hotpot_platform/cloud/sop/sop_engine.py → 集成状态机
新增: demo/data/sop_workflow.json → 7工位流转规则
```

**方案:** 
- 定义工位依赖关系：开档→收货→保存→加工→锅底→出餐→打烊
- 超时规则：工位A完成后5分钟内必须启动工位B
- 阻塞规则：工位A FAIL → 阻止工位B开始直到A RESOLVED

**工作量:** 2-3天

#### P1-3: 食材监管异常规则引擎+ERP对接

```
新增: hotpot_platform/cloud/event_hub/domain/receiving_rules.py
修改: hotpot_platform/cloud/integrations/erp_bridge.py → 真实对接
新增: hotpot_platform/cloud/event_hub/domain/supplier_quality.py
```

**工作量:** 2-3天

#### P1-4: 前厅翻台率计算

```
新增: hotpot_platform/cloud/event_hub/domain/table_history.py
修改: hotpot_platform/cloud/event_hub/domain/turnover.py
新增: hotpot_platform/cloud/event_hub/routers/turnover_stats.py
```

**工作量:** 1-2天

#### P1-5: 管理总览多店对比真实数据

```
新增: hotpot_platform/cloud/event_hub/routers/cockpit.py
修改: hotpot_platform/dashboard/cockpit.html → 接真实API
修改: hotpot_platform/dashboard/regional.html → 接真实API
```

**工作量:** 2-3天

#### P1-6: 员工行为三个子场景具体实现

```
修改: edge/staff_behavior/inference/behavior_detector.py → 完善三场景
新增: tests/test_staff_behavior.py
```

**工作量:** 3-4天

---

### 🟢 P2 — 月度计划 (4-8周)

#### P2-1: 预测性分析
- 废料趋势预测（时序模型，替换简单环比）
- 翻台率预测（基于历史均值+当前时段）
- SOP违规预测（高频违规工位→提前预警）

#### P2-2: 移动端完善
- `dashboard/mobile/` 补全管理总览移动版
- 企微小程序集成

#### P2-3: 技术债清理
- 统一 `rules.py` 为Edge Agent可下发配置
- YOLO引擎降级到 `edge/common/detector/` 减少重复
- Dashboard API URL硬编码整治（`127.0.0.1` → 可配置）

---

## 四、重构架构总览

### 目标目录结构（新增部分标 ★）

```
hotpot_smart_ops/
├── edge/
│   ├── agent/
│   │   ├── server.py              # 已有，需注册3个新模块
│   │   └── modules/
│   │       ├── kitchen_infer.py   # 已有
│   │       ├── front_hall_infer.py # 已有
│   │       ├── sop_infer.py       # ★ 新增
│   │       ├── receiving_infer.py # ★ 新增
│   │       └── staff_behavior_infer.py # ★ 新增
│   ├── kitchen/                   # 已有
│   │   └── inference/
│   │       ├── stages/
│   │       │   ├── stage_yolo.py
│   │       │   ├── stage_clip.py
│   │       │   ├── stage_vlm.py
│   │       │   ├── stage_counter.py   # ★ 新增: 计数统计
│   │       │   └── stage_sop.py       # ★ 新增: SOP合规检测
│   │       └── pipeline.py
│   ├── front_hall/                # 已有，无需大改
│   ├── receiving/                 # ★ 全新模块
│   │   └── inference/
│   │       ├── pipeline.py
│   │       └── rules.py
│   ├── staff_behavior/            # ★ 全新模块
│   │   └── inference/
│   │       ├── pipeline.py
│   │       ├── behavior_detector.py
│   │       └── rules.py
│   └── common/                    # 已有
├── hotpot_platform/
│   ├── cloud/
│   │   ├── event_hub/
│   │   │   ├── routers/
│   │   │   │   ├── waste_stats.py      # ★ 新增
│   │   │   │   ├── receiving_analyze.py # ★ 新增
│   │   │   │   ├── staff.py            # ★ 新增
│   │   │   │   ├── cockpit.py          # ★ 新增
│   │   │   │   └── turnover_stats.py   # ★ 新增
│   │   │   └── domain/
│   │   │       ├── waste_timeseries.py    # ★ 新增
│   │   │       ├── waste_cost.py         # ★ 新增
│   │   │       ├── receiving_rules.py    # ★ 新增
│   │   │       ├── supplier_quality.py   # ★ 新增
│   │   │       └── table_history.py      # ★ 新增
│   │   └── sop/
│   │       └── station_state_machine.py  # ★ 新增
│   └── dashboard/
│       └── staff.html                    # ★ 新增
└── docs/
    └── gap-analysis-v2.md               # ★ 本文档
```

### 模块注册表扩展

`edge/agent/server.py` 中 `_MODULE_REGISTRY` 扩展:

```python
_MODULE_REGISTRY = {
    "kitchen": kitchen_infer,
    "front_hall": front_hall_infer,
    "sop": sop_infer,              # ★ 新增
    "receiving": receiving_infer,  # ★ 新增
    "staff_behavior": staff_behavior_infer,  # ★ 新增
}
```

---

## 五、工作量估算

| 优先级 | 模块 | 工作项 | 估时 | 小计 |
|:---:|------|------|:---:|:---:|
| 🔴 P0 | 后厨损耗 | Count计数+趋势存储 | 3-4天 | |
| 🔴 P0 | SOP规范 | Edge合规检测管线 | 3-4天 | |
| 🔴 P0 | 食材监管 | Edge进货口检测模块 | 4-5天 | |
| 🔴 P0 | 员工行为 | Edge检测模块骨架+Dashboard | 5-7天 | **15-20天** |
| | | | | |
| 🟡 P1 | 后厨损耗 | 废料→成本闭环 | 2-3天 | |
| 🟡 P1 | SOP规范 | 工位状态机激活 | 2-3天 | |
| 🟡 P1 | 食材监管 | 异常规则+ERP对接 | 2-3天 | |
| 🟡 P1 | 前厅桌态 | 翻台率计算 | 1-2天 | |
| 🟡 P1 | 管理总览 | 多店对比真实数据 | 2-3天 | |
| 🟡 P1 | 员工行为 | 三场景具体实现 | 3-4天 | **12-18天** |
| | | | | |
| 🟢 P2 | 全部 | 预测+移动端+技术债 | 8-10天 | **8-10天** |
| | | | | |
| | | | **总计** | **35-48天** |

---

## 六、关键决策点

1. **SOP合规检测归属**: 放在 `edge/kitchen/inference/stages/stage_sop.py`（拓展现有管线） vs 独立 `edge/sop/` 模块？
   - **建议**: 放在 kitchen/stages 下，因为SOP检测场景主要在后厨区域，复用厨房摄像头和YOLO/CLIP引擎。独立模块会在Agent层多一个模块注册但本质共享同一套推理资源。

2. **员工行为用YOLO-pose还是MediaPipe**？
   - **建议**: 先用YOLO-pose（已有YOLO生态，模型小，Jetson友好），交头接耳检测用简单的头部向量夹角判断。后续精度不够再换MediaPipe。

3. **时序数据库选择**？
   - **建议**: 短期内继续用SQLite（项目已用），新增 `waste_events` 和 `table_states` 两张表。量大了再迁移到TimescaleDB。SQLite对单店百MB/年级别的时序数据足够。

4. **VLM是否每个场景都部署一套**？
   - **建议**: 不。后厨废料、食材品质、SOP合规共享同一个VLM推理进程（Ostrakon-VL-8B on Jetson），通过不同的prompt切换场景。Edge Agent的 `kitchen_infer.py` 中已有VLM子进程管理，可复用。

---

*关联文档: `docs/火锅AI-产品定位.md` · `CLAUDE.md` · `docs/archive/PRD-技术架构-v3.10.md`*
