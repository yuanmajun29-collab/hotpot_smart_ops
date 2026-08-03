# Project context for Claude Code

This file is auto-loaded by Claude Code. The section below is updated by Agent Coordinator when you run `coordinator context inject`.

## Shared state (Agent Coordinator)


---
SHARED PROJECT STATE (from other AI tools):
---

Current State:
- hermes/sync-timestamp: 20260716-163043
  (Set by: hermes)
  (Reason: 进化同步完成: 6/9 维度变化)

Recent Decisions:
- hermes: state_change - hermes/sync-timestamp
- hermes: state_change - hermes/sync-timestamp
- hermes: state_change - hermes/sync-timestamp
- hermes: state_change - hermes/sync-timestamp
- hermes: state_change - hermes/sync-timestamp

---
IMPORTANT: Before making changes that affect these values, coordinate with other tools.
If you change any of these, declare it using: declareStateChange(key, oldValue, newValue)
---


---

## 产品定位

> **火瞳**：冯校长火锅连锁AI运营中台（视觉+数据双引擎）
> - 三阶段：内部验证 → 自有扩张 → 对外输出
> - 当前：Sprint 0 已通过（椒江店 MAPE 10.6% + 玉环店损耗闭环 7/7）
> - 硬截止日：2026年10月重庆市政府展会亮相
> - 主线PRD：`docs/01-核心权威/火瞳_融合PRD_v5.3_主线基线.md`（v5.3i，129项功能，**2839行**）
> - 开发分支：`feature/d1-expo-sprint`（展会冲刺，D1冻品→D2岗位AI→D3集成→D4彩排）
> - 解决方案架构：`docs/01-核心权威/火瞳_解决方案架构设计_v1.0.md`（10章节，716行）
> - **系统架构总体设计**：`docs/01-核心权威/火瞳_系统架构总体设计_v2.0.md`（4+1视图，1478行）
> - **详细架构设计**：`docs/01-核心权威/火瞳_详细架构设计_v1.0.md`（接口+数据模型+API+协议+部署，可执行级）★NEW
> - 可行性分析：`docs/01-核心权威/火瞳_解决方案架构可行性分析_20260729.md`（6维度，71分B+，GO）

## 权威文档索引

| 文档 | 位置 | 说明 |
|------|------|------|
| 主线PRD | `docs/01-核心权威/火瞳_融合PRD_v5.3_主线基线.md` | v5.3i，唯一权威，129项功能，**2839行** |
| **系统架构总体设计** | `docs/01-核心权威/火瞳_系统架构总体设计_v2.0.md` | **★ v2.0, 4+1视图方法论, 10章节, 1478行, 架构唯一权威** |
| **详细架构设计** | `docs/01-核心权威/火瞳_详细架构设计_v1.0.md` | **★ v1.0, 接口/数据模型/API/协议/部署/监控, 可执行级** |
| 解决方案架构 | `docs/01-核心权威/火瞳_解决方案架构设计_v1.0.md` | v1.0，10章节，四层技术架构(基础文档) |
| 可行性分析 | `docs/01-核心权威/火瞳_解决方案架构可行性分析_20260729.md` | 6维度评估，71分B+，GO |
| 市场调研v2.0 | `docs/02-市场调研/火瞳_全网市场调研与可行性评估报告_v2.0_20260728.md` | 7+10家竞品+行业趋势+86分A- (基于v5.3e基线，当前PRD已迭代至v5.3i) |
| 市场调研v5.3c | `docs/02-市场调研/火瞳_PRD_v5.3c_市场调研与竞品评估报告_20260728.md` | 10家竞品+行业趋势 (基于v5.3c/63项基线，覆盖率为PRD v5.3i的49%) |
| 代码对齐表 | `docs/04-技术设计/PRD_V5_3i_CODE_ALIGNMENT.md` | v5.3i-rev1全量129项+6基础设施代码状态矩阵(2026-08-03实码刷新, 覆盖率36.3%) |
| 产品设计分析 | `docs/03-产品设计/产品设计-全面分析.md` | 小居8维分析(82/100)·基于v5.3d |
| 项目全貌 | `docs/03-产品设计/项目全貌-深度理解.md` | 574行9节2附录·v5.3d→v5.3i演进 |

> ⚠️ 注意: 市场调研/代码对齐/产品分析等文档基于不同时期PRD版本，功能总数/ROI/回本周期口径存在差异。以主线PRD v5.3i数字为准。
| 数据引擎设计 | `docs/04-技术设计/火锅AI-数据引擎技术设计-v1.0.md` | N01-N06技术设计，1431行 |
| 项目基线 | `docs/04-技术设计/PROJECT_BASELINE_V5_2.md` | 产品定位与边界 |
| 展会方案 | `docs/07-业务参考/火瞳_重庆展会Demo方案_v1.0.md` | 10月展会5场景+D1-D4冲刺 |
| 门店标准 | `docs/07-业务参考/火瞳_浙江总代门店标准与权益包_v1.0.md` | 定价+权益 |
| 功能规格 | `docs/05-功能规格/` | spec×5 + test_cases×3 + review×2 (10份) |
| 调研照片 | `docs/06-调研照片/` | 6区域35张实地照片 |
| **评审记录** | `docs/08-评审/` | 小居全面评审(B+ 78.8/250) + 小抠数据审查(7维度) |

---

## 项目架构

```
hotpot_smart_ops/
├── deploy/             # 部署（源码端 → 板端）
│   ├── jetson/         #   Jetson 板端：deploy.sh + build.sh
│   ├── cloud/          #   云端：docker compose
│   └── bridge/         #   VLM→Hub 桥接
├── hotpot_platform/    # 云平台（Hub + Dashboard + 数据引擎）
│   ├── cloud/
│   │   ├── data_engine/      # 🆕 v5.0 数据引擎 (N01-N06)
│   │   │   ├── models.py     #   Pydantic 数据模型
│   │   │   ├── sales_predictor.py   #   N01: AI销量预测
│   │   │   ├── order_advisor.py     #   N02: 智能订货
│   │   │   ├── inventory_book.py    #   N03: 库存台账
│   │   │   ├── loss_analyzer.py     #   N04: 损耗分析
│   │   │   ├── supplier_scorer.py   #   N05: 供应商评分
│   │   │   ├── erp_connector.py     #   N06: ERP连接器
│   │   │   ├── feature_store.py     #   特征工程
│   │   │   └── algorithms/        # 四级算法
│   │   │       └── baseline.py      #   L1-L4 预测+订货算法
│   │   ├── event_hub/
│   │   │   ├── ... (已有)
│   │   │   ├── data_engine_schema.py  # 🆕 6张新表DDL
│   │   │   └── routers/
│   │   │       └── inventory.py     # 🆕 N01-N06 API路由
│   │   └── integrations/
│   │       ├── pos_bridge.py        # ★ 扩展: per-SKU销量
│   │       └── erp_bridge.py        # ★ 扩展: 双向同步
├── edge/               # 边缘端（按场景 → 功能块）
│   ├── agent/          #   调度层（FastAPI :9100）
│   ├── front_hall/     #   场景：前厅
│   │   ├── inference/  #     ├ 推理（可插拔策略 + 引擎注册表）
│   │   │   ├── strategies/ #  ├── 策略（plan_b / plan_a，丢文件即注册）
│   │   │   ├── engines/    #  ├── 引擎（yolo + clip，懒加载）
│   │   │   ├── rules.py    #  ├── 推理规则（独立配置）
│   │   │   └── pipeline.py #  └── 统一入口
│   │   ├── iot/        #     ├ IoT 模拟（传感器/门禁）
│   │   └── bridge/     #     └ 桥接（store_forward）
│   ├── kitchen/        #   场景：后厨
│   │   ├── inference/  #     ├ 推理（可插拔管线级 + 引擎脚本）
│   │   │   ├── stages/      # ├── 管线级（yolo/clip/vlm，丢文件即注册）
│   │   │   ├── rules.py     # ├── 推理规则（阈值/提示词/降级矩阵）
│   │   │   └── pipeline.py  # └── 调度入口
│   │   ├── capture/    #     ├ 图像采集（IPC）
│   │   └── bridge/     #     └ 桥接（waste_vision → Hub）
│   ├── common/         #   共用（detector / config / models）
│   └── legacy/         #   废弃代码归档
├── docs/               # 方案文档
└── tests/              # 自动化测试
```

## 前厅场景分析

**文件**: `edge/front_hall/inference/scene_analyzer.py` + `clip_server.py`
**API**: `POST /api/scene/analyze?mode=plan_a|plan_b&table_id=T01` (`edge/agent/modules/front_hall_infer.py`)

| 模式 | 策略 | 耗时 | 依赖 |
|------|------|------|------|
| plan_b（默认） | YOLO 规则推断 | ~40ms | YOLO only |
| plan_a | YOLO 硬判决 + CLIP 语义 | 40-190ms | YOLO + CLIP 子进程 |

**策略**: YOLO 检测人头 → 没人+少餐具=empty，没人+多餐具(≥3)=needs_cleaning，有人→CLIP 语义细分
**CLIP**: 独立子进程（cwd=/tmp 绕开 hotpot_platform/ 污染），stdin/stdout JSON 通信，模型常驻

## Edge 服务器启动

```bash
cd <project_root> && python3 -m uvicorn edge.agent.server:app --host 0.0.0.0 --port 9100
```

## 设备管理层级 + 模块化配置

```
大区(Zone) → 区域(Region) → 门店(Store) → Device(推理设备, N个)
                                               └── modules:
                                                     kitchen: [cam1, cam2]
                                                     front_hall: [cam3]
```

设备直连 Hub，按模块配置。平台端可随时增减模块或调整 camera 列表。

**配置下发流**（平台→Hub→设备）：

```
管理员 PUT /v1/devices/{id}/config → modules 配置
       ↓ Hub 标记 config_pending=True
设备 register → 返回已有 config（登录即加载）
设备 heartbeat → 返回待下发 config（运行时增量推送）
设备 POST /v1/devices/{id}/pull-config → 主动拉取（更及时）
       ↓ apply_device_config(config)
       ↓ 按 enabled 启停模块 + 写 IPC 配置
```

| 端点 | 说明 |
|------|------|
| `POST /v1/devices/register` | 设备注册，返回 config.modules |
| `POST /v1/devices/{id}/heartbeat` | 心跳续期，返回待下发 config |
| `POST /v1/devices/{id}/pull-config` | 设备主动拉配置 |
| `PUT /v1/devices/{id}/config` | 管理员推送模块化配置 |
| `GET /v1/devices/{id}` | 设备详情+当前配置 |
| `GET /v1/devices?zone_id=&region_id=&store_id=` | 按层级过滤设备 |

**模块配置格式**（Platform→设备下发）：

```json
{
  "modules": {
    "kitchen": {"enabled": true, "cameras": ["rtsp://..."], "inference_interval": 30, "rules": {}},
    "front_hall": {"enabled": false, "cameras": [], "inference_interval": 30, "rules": {}},
    "sop": {"enabled": false, "cameras": [], "inference_interval": 30, "rules": {}},
    "staff_behavior": {"enabled": false, "cameras": [], "inference_interval": 30, "rules": {}},
    "receiving": {"enabled": false, "cameras": [], "inference_interval": 30, "rules": {}},
    "iot_food_safety": {"enabled": false, "sensors": [], "alert_thresholds": {}}
  }
}
```

## 已实现模块清单 (2026-08-03 刷新)

### 视觉AI引擎（28功能）
| 模块 | 路径 | PRD ID | 状态 |
|------|------|--------|------|
| 后厨损耗检测 | `edge/kitchen/inference/` + `capture/` | K01-K03 | 代码基础 |
| 前厅桌态分析 | `edge/front_hall/inference/` | K04-K05 | 代码基础 |
| 出品质检 | `edge/kitchen/inference/stages/` | K31 | 代码基础 |
| 设备管理 | `hotpot_platform/` | K06-K08 | 代码基础 |
| SOP 合规检测 | `edge/agent/modules/sop_infer.py` + `sop_engine/checker.py` | K09-K10, K27 | 代码基础 |
| 员工行为识别 | `edge/agent/modules/staff_behavior_infer.py` | K25-K26 | 代码基础 |
| 收货质检 | `edge/receiving/detector.py` + `ingredient_quality.py` + `sop_compliance.py` | K11-K12 | 代码基础 |
| IoT 食安 | `edge/iot_mock/` + `edge/front_hall/iot/` | K19-K22 | 代码基础 |
| 数据分析层 | `hotpot_platform/analytics/` | K23-K24 | 代码基础 |
| 多店/区域看板 | `hotpot_platform/` dashboard | K15, K29 | 代码基础 |

### 数据引擎（N01-N06）
| 模块 | 路径 | PRD ID | 状态 |
|------|------|--------|------|
| 销量预测 | `data_engine/sales_predictor.py` | N01 | Sprint 0 验证通过 (MAPE 10.6%) |
| 智能订货 | `data_engine/order_advisor.py` | N02 | 原型/规则骨架 |
| 库存台账 | `data_engine/inventory_book.py` | N03 | 原型/规则骨架 |
| 损耗分析 | `data_engine/loss_analyzer.py` | N04 | 原型/规则骨架，玉环14天闭环Pass |
| 供应商评分 | `data_engine/supplier_scorer.py` | N05 | 原型/规则骨架 |
| ERP连接器 | `data_engine/erp_connector.py` | N06 | 原型/规则骨架 |

### 供应链（S01-S04）★ 新增
| 模块 | 路径 | PRD ID | 状态 |
|------|------|--------|------|
| 货品主数据管理 | `cloud/supply_chain/manager.py`(4416行) + `scripts/migrate_product_master.py` + `edge-ui/api/product_master_api.py` | S01 | 代码基础 |
| 冻品收货验收 | `edge/receiving/`(9文件) + `event_hub/routers/receiving.py` + `edge-ui/api/receiving_api.py` | S02 | 代码基础 |
| 供应商协同/退换货 | `event_hub/routers/supply_chain.py` + `edge-ui/api/supplier_api.py` + `data_engine/supplier_scorer.py` | S03 | 代码基础 |
| 冻品温控追溯 | `cloud/warehouse/`(inventory_alertor/fefo_monitor/rfid_tracker/iot_monitor) + `event_hub/routers/inventory.py` | S04 | 代码基础 |

### AI助理框架（A01-A03）★ 新增
| 模块 | 路径 | PRD ID | 状态 |
|------|------|--------|------|
| 店长AI助理 | `agent_framework/`(gateway/orchestrator/action_types/models,2253行) + `cockpit/`(dashboard/models) + `edge-ui/api/assistant_api.py` | A01 | 代码基础 |
| 后厨AI助理 | `sop_engine/`(checker/template_manager/models) + `edge/kitchen/inference/`(pipeline/anomaly_infer) + `agent/modules/kitchen_infer.py` | A02 | 代码基础 |
| 采购AI助理 | `event_hub/routers/purchase_cycle.py`(1340行) + `edge-ui/api/purchase_order_api.py` + `data_engine/order_advisor.py` + `erp_connector.py` | A03 | 代码基础 |

### 基础设施 ★ 新增
| 模块 | 路径 | 说明 |
|------|------|------|
| Agent Gateway | `agent_framework/agent_gateway.py` + `alert_gateway/gateway.py` + `middleware/gateway.py` | 统一行动权限控制+审计日志 |
| JWT/RBAC 统一认证 | `middleware/auth_unified.py` + `auth_adapter.py` + `rbac.py` + `auth_routes.py` + `edge-ui/api/auth_api.py` | 全系统身份鉴权(1921行) |
| 待清台闭环MVP | `front_hall/inference/vision_worker.py` + `middleware/task_escalator.py` + `dashboard/cleaning-tasks.html` + T1-T4测试(70个) | 前厅桌态→任务→H5接单→升级 |
| 数据同步 | `cloud/data_sync.py` | Edge↔Hub数据同步框架 |
| PG Schema初始化 | `cloud/db_init.py` | 数据库自动初始化 |
| Edge UI 主入口 | `edge-ui/main.py`(FastAPI) + 15 API | 边缘端统一Web服务(:9080) |

### 集成层
| 模块 | 路径 | 状态 |
|------|------|------|
| POS per-SKU | `pos_bridge.fetch_sku_sales()` | ✅ done |
| ERP 双向同步 | `erp_bridge.push_*()` | ✅ done |
| API 路由 | `routers/inventory.py` | ✅ done |
| DB 表 (6张) | `data_engine_schema.py` | ✅ done |

## 待建模块 (PRD v5.3i · 展会冲刺 D1-D4, 2026-08-03 刷新)

> 以下为 **尚未具备代码基础** 的模块。S01/S03/A01-A03/S04 已移至「已实现模块清单」。

| 模块 | PRD ID | 优先级 | Sprint | 备注 |
|------|--------|:------:|:------:|------|
| 冻品收货验收(真实VLM) | S02 | P0 | D1 | 接口已有，Mock→真实VLM桥接待补 |
| 供应链场景编排 | SC01 | P0 | — | 无代码 |
| 知识库工具链 | KT01 | P0 | — | 无代码 |
| 供应商协同端 | A04 | P2 | 展会后 | 无代码 |
| 知识库助理 | A05 | P1 | 展会后 | 框架骨架 |
| 跨店库存调拨 | N19 | P1 | 展会后 | 无代码 |
| 供应商协同群 | N20 | P1 | 展会后 | 无代码 |
| 库位管理 | N21 | P1 | 展会后 | 无代码 |
| AI菜品推荐 | N22 | P1 | 展会后 | 无代码 |
| 会员消费分析 | N18 | P1 | 展会后 | 无代码 |
| 出品率管控 | K35 | P1 | 展会后 | 无代码 |
| 主动服务提醒 | K33 | P1 | 展会后 | 无代码 |
| 耗材监控 | K34 | P1 | 展会后 | 无代码 |
| 库位定点标识 | K36 | P1 | 展会后 | 无代码 |
| 后厨扩展(K38-K42) | K38-K42 | P1 | 展会后 | 无代码 |
| 前厅排队管理 | FH01 | — | — | 无代码 |
| 前厅会员识别 | FH02 | — | — | 无代码 |
| 连锁管控(H01-H14) | H01-H14 | Phase 2 | Phase 2 | 无代码 |
| 区域功能(N13-N16) | N13-N16 | Phase 2 | Phase 2 | 无代码 |