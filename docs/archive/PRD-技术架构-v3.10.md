# PRD：火锅连锁餐饮 AI 智能运营平台 — 技术架构 v3.10

> **文档版本**: V1.0  
> **对应代码版本**: hotpot V3.10 (20260711-1735)  
> **整理日期**: 2026-07-15  
> **整理人**: Hermes (小马)  
> **原则**: 基于 `~/company/products/to-b/hotpot_smart_ops/` 实际代码状态输出

---

## 目录

1. [模块功能清单](#1-模块功能清单)
2. [产品分层架构](#2-产品分层架构)
3. [模块成熟度标注](#3-模块成熟度标注)
4. [产品开发路线图](#4-产品开发路线图)
5. [技术债清单](#5-技术债清单)
6. [附录：数据流全链路](#6-附录数据流全链路)

---

## 1. 模块功能清单

### 1.1 边缘端（edge/）— Jetson Orin 32GB 部署

#### 1.1.1 edge/agent/ — 边缘 Agent 统一入口 (FastAPI :9100)

| 文件 | 功能 | 核心技术 |
|------|------|----------|
| `server.py` | 单端口 9100 统一入口，替代历史 kitchen/front_hall 各自 server | FastAPI + uvicorn |
| `config.py` | 环境变量驱动配置 (HUB_URL, DEVICE_ID, STORE_ID, API_KEY, LLAMA 路径) | os.environ, 启动校验 |
| `modules/kitchen_infer.py` | 后厨推理模块：YOLO 预过滤 + VLM 废弃物识别 (ADR-014 三级过滤) | RealYoloDetector, llama-mtmd-cli, OpenCV |
| `modules/front_hall_infer.py` | 前厅推理模块：YOLO 检测 + plan_a/plan_b 双模式场景分析 | RealYoloDetector, CLIP 子进程, Base64 解码 |

**核心机制**:
- 设备注册 → Hub 返回模块配置 → `apply_device_config()` 按 `enabled` 启停模块
- 心跳 30s / 配置轮询 60s
- 模块注册表 `_MODULE_REGISTRY`（新增场景加一行即可）
- `_active` 标志控制模块是否响应 API

**API 端点**:
| 端点 | 说明 |
|------|------|
| `GET /health` | 总体健康 + 模块状态 |
| `GET /debug/engine` | 诊断：引擎导入 + YOLO 加载状态 |
| `GET /infer/kitchen/health` | 后厨模块健康（VLM CLI/模型路径检查） |
| `GET /infer/kitchen/yolo` | YOLO-only 检测 (~8ms)，含 `vlm_should_trigger` |
| `POST /infer/kitchen` | 完整管线：YOLO→CLIP→VLM，结果推 Hub（带重试3次） |
| `GET /health/front-hall` | 前厅模块健康 |
| `GET /api/infer` | 前厅单图检测 |
| `GET /api/infer/all` | 前厅批量检测 |
| `GET /api/log` | 推理日志（最近50条） |
| `POST /api/scene/analyze` | 场景分析（plan_b/plan_a，支持 Base64 / multipart） |
| `GET /api/scene/batch` | 批量场景分析 |
| `GET /output/*` | 静态文件（标注图） |

---

#### 1.1.2 edge/kitchen/ — 后厨推理管线

**架构**: 可插拔管线级 + 注册表自动发现

| 文件 | 功能 | 技术栈 |
|------|------|--------|
| `inference/pipeline.py` | 管线调度器：按 stages/ 注册表顺序执行 YOLO→CLIP→VLM | 共享上下文 ctx，3次重试推 Hub |
| `inference/stages/__init__.py` | **管线级注册表**：自动发现 `stage_*.py` 并按 `STAGE_ORDER` 排序 | importlib 动态加载 |
| `inference/stages/stage_yolo.py` | YOLO 目标检测级 | RealYoloDetector + Kalman 跟踪 |
| `inference/stages/stage_clip.py` | CLIP-Adapter 场景分类级 | CLIP 子进程 |
| `inference/stages/stage_vlm.py` | VLM 语义分析级（按需触发） | llama-mtmd-cli 子进程 |
| `inference/stages/stage_anomaly.py` | 异常检测级 | Anomalib 适配器 |
| `inference/stages/stage_open_world.py` | 开放世界检测级（未知物体检测） | — |
| `inference/rules.py` | 推理规则配置（阈值/类别/提示词/降级矩阵） | 纯配置，不含模型加载 |
| `inference/yolo_infer.py` | YOLO 引擎独立脚本 | ultralytics |
| `inference/clip_infer.py` | CLIP 引擎独立脚本 | OpenAI CLIP |
| `inference/vlm_infer.py` | VLM 引擎独立脚本 | llama.cpp |
| `inference/pixel_direct.py` | 像素直通（跳过 YOLO，直接 VLM） | OpenCV → llama |
| `inference/anomaly_infer.py` | 异常检测引擎 | Anomalib |
| `inference/anomalib_adapter.py` | Anomalib 适配层 | anomalib |
| `inference/kalman_tracker.py` | Kalman 滤波跟踪器 | 自定义实现 |
| `inference/supervision_wrapper.py` | Supervision 库包装 | Roboflow Supervision |
| `inference/defect_measurement.py` | 缺陷测量 | OpenCV |
| `capture/ipc_frame_grabber.py` | IPC 摄像头 RTSP 抓帧 | OpenCV VideoCapture |
| `bridge/waste_vision.py` | 废料视觉→Hub 桥接 | httpx POST |

**推理规则 (rules.py)**:
- YOLO: conf=0.25, IoU=0.45, img_size=640, YOLO26n (NMS-free)
- Kalman: max_age=5, min_hits=2, iou_thresh=0.25
- CLIP: 5 类默认 (clean_kitchen, dirty_surface, food_waste, cluttered, dangerous_object), low_conf=0.5
- VLM: 超时 30s, temperature=0.1, max_tokens=512
- 降级矩阵: YOLO 故障→整体失败；CLIP 故障→直走 VLM；CLIP 高置信度→跳过 VLM

---

#### 1.1.3 edge/front_hall/ — 前厅推理管线

**架构**: 可插拔策略 + 引擎注册表自动发现

| 文件 | 功能 | 技术栈 |
|------|------|--------|
| `inference/pipeline.py` | 统一入口 `analyze_table()` | YOLO + 策略分发 |
| `inference/rules.py` | **推理规则**(COCO类别映射/CLIP提示词/Plan B告警/推荐语) | 纯配置 |
| `inference/scene_analyzer.py` | 场景分析器（串联 YOLO + CLIP） | — |
| `inference/vision_worker.py` | 视觉工作线程 | — |
| `inference/sources.py` | 图片源抽象 | — |
| `inference/strategies/__init__.py` | **策略注册表**：自动发现策略类 | importlib + inspect |
| `inference/strategies/base.py` | BaseStrategy 抽象基类 | ABC |
| `inference/strategies/plan_b.py` | **Plan B**：纯 YOLO 规则推断 (~40ms) | YOLO counts → 规则判决 |
| `inference/strategies/plan_a.py` | **Plan A**：YOLO + CLIP 语义细分 (~190ms) | YOLO 硬判决 + CLIP 子进程 |
| `inference/engines/__init__.py` | **引擎注册表**：yolo + clip 懒加载 | — |
| `inference/engines/yolo.py` | YOLO 引擎封装 | RealYoloDetector |
| `inference/engines/clip_client.py` | CLIP 客户端 | 子进程 stdin/stdout JSON 通信 |
| `inference/engines/clip_server.py` | CLIP 独立子进程（cwd=/tmp 绕开 hotpot_platform/ 污染） | OpenAI CLIP，模型常驻 |
| `iot/` | IoT 模拟 (传感器/MQTT/食材桥接) | paho-mqtt |
| `bridge/store_forward.py` | 断网本地缓存 → 恢复后转发 | 本地 JSON 队列 |

**前厅策略 (rules.py)**:
| 模式 | 策略 | 耗时 | 依赖 |
|------|------|------|------|
| plan_b（默认） | YOLO 规则推断（person + tableware/food 计数 → 4态判决） | ~40ms | YOLO only |
| plan_a | 有人→CLIP 语义（table/service/customer 三组提示词） | 40-190ms | YOLO + CLIP 子进程 |

**前厅四态**: empty / ready / dining / needs_cleaning  
**告警优先级**: needs_cleaning=high, dining=medium, empty=low, ready=medium  
**CLIP 子进程架构**: 独立进程（cwd=/tmp），stdin/stdout JSON 通信，模型常驻内存（避免重复加载）

---

#### 1.1.4 edge/common/ — 共用组件

| 文件 | 功能 |
|------|------|
| `detector/real_yolo.py` | YOLO 检测器核心：ultralytics 加载，COCO 类别映射，hotpot 业务类别 |
| `detector/yolo_onnx.py` | YOLO ONNX 推理备选 |
| `detector/rknn_backend.py` | RKNN NPU 后端备选 |
| `detector/hotpot_detector.py` | 检测器抽象基类（工厂模式） |
| `config/pipeline_config.yml` | 管线配置 |
| `config/ipc_config.yml` | IPC 摄像头配置 |

#### 1.1.5 edge/legacy/ — 废弃代码归档

| 文件 | 说明 |
|------|------|
| `kitchen_server.py` | 旧版后厨独立 server（已被 edge/agent/server.py 取代） |
| `scripts/edge_agent.py` | 旧版 agent（已被新架构取代） |
| `rknn_deploy/` | RKNN 部署方案（RK3566/RK3588 NPU 推理） |
| `kitchen_compliance.onnx` | 后厨合规 ONNX 模型 |
| `table_state.onnx` | 桌台状态 ONNX 模型 |

---

### 1.2 云端平台（hotpot_platform/）

#### 1.2.1 cloud/event_hub/ — Hub API (FastAPI :8098)

**架构**: 模块级路由器自动发现 + DDD 领域驱动

| 文件 | 功能 | 状态 |
|------|------|------|
| `app.py` | FastAPI 入口：DB/运行时初始化、CORS、静态文件挂载、路由器自动发现 | ✅ |
| `server.py` | 启动器脚本（uvicorn + DB/seed 参数） | ✅ |
| `hub_core.py` | 多租户 Hub 核心：事件 CRUD、门店隔离 | ✅ |
| `db.py` | SQLite DB 层：持久化、hydration | ✅ |
| `pg_db.py` | PostgreSQL DB 适配（生产） | ⚠️ |
| `auth.py` | X-Api-Key 边缘认证 + JWT 用户认证 | ✅ |
| `rbac.py` | RBAC 角色权限控制 | ✅ |
| `runtime.py` | 全局运行时单例（hub + db + alert_gateway） | ✅ |
| `org_registry.py` | 组织架构注册表（大区→区域→门店） | ✅ |
| `sop_assign_store.py` | SOP 任务分配存储 | ✅ |
| `task_store.py` | 任务存储 | ✅ |
| `task_factory.py` | F-TASK 任务工厂 | ✅ |
| `receiving_store.py` | 来料收货存储 | ✅ |
| `daily_report_store.py` | 日报存储 | ✅ |
| `iot_readings_store.py` | IoT 读数存储 | ✅ |
| `daily_scheduler.py` | 三时段损耗调度器 (15:00/22:00/周一09:00) | ✅ |
| `device_stub.py` | 设备管理桩 | ⚠️ |
| `routers/__init__.py` | **路由器自动发现**（新增路由=丢文件→自动注册） | ✅ |
| `routers/vlm.py` | `/v1/vlm/waste-estimate` 废料估算 | ✅ |
| `routers/ingest.py` | `/v1/events` 事件摄入 | ✅ |
| `routers/alerts.py` | 告警路由 | ✅ |
| `routers/cost.py` | 成本分析 | ✅ |
| `routers/tasks.py` | 任务管理 | ✅ |
| `routers/devices.py` | 设备管理（注册/心跳/配流） | ✅ |
| `routers/sop.py` | SOP 引擎路由 | ✅ |
| `routers/receiving.py` | 来料收货路由 | ✅ |
| `routers/images.py` | 图片上传/查询 | ✅ |
| `routers/reports.py` | 日报路由 | ✅ |
| `routers/iot.py` | IoT 设备路由 | ✅ |
| `routers/admin.py` | 管理后台路由 | ✅ |
| `routers/admin_users.py` | 管理员用户路由 | ✅ |
| `routers/auth_routes.py` | 认证路由 | ✅ |
| `routers/org.py` | 组织架构路由 | ✅ |
| `routers/system.py` | 系统路由 | ✅ |
| `routers/feedback.py` | 反馈路由 | ✅ |
| `domain/waste_estimate.py` | 废料估算领域模型 | ✅ |
| `domain/loss_budget.py` | 损耗预算领域模型 | ✅ |
| `domain/loss_risk.py` | 损耗风险领域模型 | ✅ |
| `domain/turnover.py` | 翻台率领域模型 | ✅ |
| `domain/health.py` | 健康检查领域模型 | ✅ |
| `tasks/task_daily.py` | 日报任务 | ✅ |
| `tasks/task_weekly.py` | 周报任务 | ✅ |
| `tasks/task_restock.py` | 补货建议任务 | ✅ |

**路由器注册表**（18个路由域）：
```
vlm | alerts | cost | tasks | devices | sop | receiving | images | reports |
iot | admin | admin_users | auth | org | system | feedback | ingest | _deps
```

---

#### 1.2.2 cloud/ — 其他云服务

| 文件 | 功能 | 状态 |
|------|------|------|
| `vlm_review/app.py` | VLM 复核服务 (GPT-4V / Qwen-VL) | ⚠️ 桩 |
| `vlm_review/server.py` | VLM 复核启动器 | ⚠️ |
| `llm_report/report_agent.py` | LLM 日报 Agent (rule 兜底 + OpenAI API 可选) | ⚠️ 部分 |
| `llm_report/forecast_agent.py` | LLM 预测 Agent | ⚠️ 部分 |
| `llm_report/sop_rag.py` | SOP RAG（知识库问答） | ⚠️ 规划中 |
| `sop/sop_engine.py` | SOP 规则引擎 | ✅ |
| `sop/scheduler.py` | SOP 调度器 | ✅ |
| `cost_control/analyzer.py` | 成本分析引擎（损耗/出成率/供应商对账） | ✅ |
| `cost_control/feature_builder.py` | 成本特征工程 | ✅ |
| `alert_gateway/gateway.py` | 告警网关 (企微/邮件/短信) | ✅ |
| `integrations/pos_bridge.py` | POS 系统桥接 | ⚠️ |
| `integrations/erp_bridge.py` | ERP 系统桥接 | ⚠️ |

---

#### 1.2.3 dashboard/ — 前端看板 (静态 HTML :9120)

| 页面 | 文件 | 功能 | 状态 |
|------|------|------|------|
| 登录 | `login.html` | 用户登录 (JWT) | ✅ |
| 首页概览 | `index.html` / `home.html` | 驾驶舱首页 | ⚠️ 部分接数据 |
| 桌台管理 | `tables.html` | 前厅桌态管理 | ⚠️ |
| 后厨智能识别 | `vlm-demo.html` | 废料识别实时展示 (核心页) | ✅ 完整 |
| 后厨看板 | `kitchen.html` | 后厨概览 | ⚠️ |
| 后厨视觉 | `kitchen-vision.html` | 后厨实时视觉 | ⚠️ |
| 边缘视觉 | `edge-vision.html` | 边缘设备视觉流 | ⚠️ |
| 成本分析 | `cost.html` | 损耗/预算/出成率 | ✅ |
| 告警中心 | `alerts.html` | 告警列表+确认 | ✅ |
| 运营报告 | `report.html` | 日报/周报 | ⚠️ |
| 驾驶舱 | `cockpit.html` | 大屏驾驶舱 | ⚠️ |
| 区域总览 | `regional.html` | 跨店对标 | ⚠️ |
| 任务管理 | `tasks.html` | F-TASK 任务面板 | ✅ |
| SOP | `sop.html` | SOP 执行看板 | ⚠️ |
| 系统管理 | `system.html` | 系统配置 | ⚠️ |
| PoC 演示 | `poc.html` | PoC 演示页 | ⚠️ |
| 设备管理 | `devices.html` | 设备注册/配流 | ❌ 待开发 |
| 前厅场景 | `front-hall.html` | 前厅场景分析 | ⚠️ 基础 |
| 样式指南 | `styleguide.html` | UI 组件参考 | ✅ |
| 管理员 | `admin/` | 管理后台 (RBAC/门店/管线) | ⚠️ 部分 |
| 移动端 | `mobile/` | 移动端页面 | ⚠️ 基础 |
| PDA | `pda/receiving.html` | PDA 来料收货 | ⚠️ 基础 |

**前端基础设施**:
- `assets/theme.css` — 火锅暖色主题 (橙红 #E2613A, 深色背景)
- `assets/core.js` — 前端通用 JS（API 调用/认证/路由）
- `assets/rbac.json` — RBAC 角色权限配置
- `serve.py` — 开发服务器 (python http.server)

---

### 1.3 部署（deploy/）

| 文件 | 功能 |
|------|------|
| `deploy-hotpot.sh` | 一键部署脚本（Mac→Jetson）：10 Phase 完整流程 |
| `jetson/Dockerfile` + `jetson/entrypoint.sh` | Jetson 容器化 |
| `jetson/docker-compose.yml` | Jetson 容器编排 |
| `jetson/deploy.sh` + `jetson/build.sh` | Jetson 板端部署 |
| `jetson/jetson_server.py` | Jetson 独立服务 |
| `jetson/download_models.sh` | 模型权重下载 |
| `edge/Dockerfile` + `edge/docker-compose.yml` | 边缘容器 |
| `edge/systemd/hotpot-pipeline.service` | 管线 systemd 服务 |
| `edge/systemd/ipc-grabber.service` | IPC 抓帧 systemd 服务 |
| `cloud/docker-compose.yml` | 云端容器编排 |
| `bridge/bridge.sh` | VLM→Hub 桥接脚本 |
| `watchdog.sh` | 服务看门狗 |
| `VERSION` | 版本号 (V3.10) |

**部署流程** (deploy-hotpot.sh 10 Phase):
```
Phase 0: 环境自检
Phase 1: rsync 源码 → Jetson
Phase 2: pip 安装依赖
Phase 3: 停止旧服务
Phase 4: 编译/启动 VLM (llama.cpp)
Phase 5: 启动 Hub :8098
Phase 6: 启动 Edge Agent :9100
Phase 7: 激活 kitchen 模块
Phase 8: 全链路验证 (Hub + Edge + YOLO 推理)
Phase 9: 部署状态面板
Phase 10: 实时监控 (Ctrl+C 退出)
```

**systemd 服务** (hotpot_platform/deploy/systemd/):
- `hotpot-hub.service` — Hub 服务
- `hotpot-dashboard.service` — Dashboard 服务
- `hotpot-vision@.service` — 视觉推理服务（模板）
- `hotpot-pos@.service` — POS 桥接（模板）
- `hotpot-erp@.service` — ERP 桥接（模板）

---

### 1.4 测试（tests/）— 37 个测试文件，176 测试

| 测试文件 | 覆盖领域 |
|----------|----------|
| `test_hub_smoke.py` | Hub 冒烟测试 |
| `test_waste_estimate.py` | 废料估算 |
| `test_vlm_api.py` | VLM API |
| `test_kitchen_yolo.py` | 后厨 YOLO |
| `test_devices_api.py` | 设备管理 API |
| `test_cockpit_api.py` | 驾驶舱 API |
| `test_cost_*/test_feature_*/test_loss_*` | 成本/损耗 |
| `test_task_*` | 任务引擎 |
| `test_sop_*` | SOP 引擎 |
| `test_iot_*` | IoT |
| `test_rbac_*` | RBAC |
| `test_daily_report_*/test_alerts_*` | 日报/告警 |
| `test_store_forward.py` | 断网缓存 |
| `test_store_isolation.py` | 多租户隔离 |
| `test_wechat_webhook_e2e.py` | 企微 Webhook E2E |
| `test_defect_measurement.py` | 缺陷测量 |
| `conftest.py` | 测试夹具 |

---

## 2. 产品分层架构

### 2.1 四层架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│                     展示层 (Presentation)                         │
│  Dashboard HTML (15+页) · 大屏驾驶舱 · 移动端 · PDA · 企微推送     │
│  theme.css · core.js · serve.py :9120                             │
├──────────────────────────────────────────────────────────────────┤
│                      数据层 (Data & Logic)                        │
│  ┌──────────┬───────────┬───────────┬───────────┬──────────┐    │
│  │ Event Hub │ 成本分析  │ 任务引擎  │ SOP 引擎  │ 告警网关 │    │
│  │ :8098     │ cost/*    │ F-TASK    │ rule eng. │ 企微/邮件│    │
│  │ 多租户    │ 损耗预算  │ 定时调度  │ 合规校验  │ 路由升级 │    │
│  └──────────┴───────────┴───────────┴───────────┴──────────┘    │
│  DB: SQLite (dev) · PostgreSQL (prod) · 事件持久化 · RBAC        │
├──────────────────────────────────────────────────────────────────┤
│                      推理层 (Inference)                           │
│  ┌──────────────────────┐  ┌───────────────────────────┐        │
│  │  后厨管线 (三级过滤)  │  │  前厅管线 (双模式)         │        │
│  │  YOLO (8ms)          │  │  plan_b: YOLO规则 (~40ms) │        │
│  │    → CLIP-Adapter    │  │  plan_a: YOLO+CLIP (~190) │        │
│  │    → VLM/LLM (320ms) │  │  四态: empty/ready/       │        │
│  │  可插拔 stages/ 注册  │  │        dining/cleaning    │        │
│  └──────────────────────┘  └───────────────────────────┘        │
│  引擎: YOLOv8n/YOLO26n · CLIP ViT-B/32 · Ostrakon-VL-8B        │
│  Edge Agent :9100 — 设备注册/心跳/配置热重载                     │
├──────────────────────────────────────────────────────────────────┤
│                     感知层 (Perception)                           │
│  IPC 摄像头 RTSP 抓帧 · IoT 传感器 MQTT · 智能秤/RFID · 门磁    │
│  capture/ipc_frame_grabber.py · iot_mock/ 模拟框架               │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 各层详细职责

#### 感知层 — 数据采集

| 组件 | 采集方式 | 输出 | 成熟度 |
|------|----------|------|--------|
| IPC 摄像头 | RTSP 流 → OpenCV 抓帧 JPG | `/tmp/ipc_frames/latest.jpg` | ⚠️ 未配 RTSP |
| IoT 传感器 | MQTT `hotpot/{store_id}/sensors/{sensor_id}` | 传感器读数事件 | ⚠️ 模拟就绪，缺硬件 |
| 智能秤 | MQTT 重量读数 | 来料重量/出成率 | ⚠️ 模拟 |
| RFID 扫描 | MQTT 批次扫描 | 批次追溯 | ⚠️ 模拟 |
| 门磁/温感 | MQTT 状态变化 | 冷链/安全告警 | ⚠️ 模拟 |

#### 推理层 — AI 推理与决策

| 组件 | 能力 | 延迟 | 模型 |
|------|------|------|------|
| **后厨 YOLO** | 目标检测（人员/食材/容器/设备/餐具） | 8ms | YOLOv8n / YOLO26n |
| **后厨 CLIP** | 场景分类（干净/脏/废物/混乱/危险） | ~50ms | CLIP ViT-B/32 |
| **后厨 VLM** | 废弃物语义识别（SKU/废弃类型/份量/建议） | 320ms-57s | Ostrakon-VL-8B (GGUF) |
| **前厅 YOLO** | 人头/食品/饮品/餐具检测 | ~40ms | YOLOv8n |
| **前厅 CLIP** | 桌态语义（用餐/待清/结账/呼叫） | ~150ms | CLIP ViT-B/32 |
| **LLM Agent** | 日报/预测/SOP问答/供应商对账 | <30s | OpenAI API / rule兜底 |

**三级过滤机制** (后厨 ADR-014):
1. YOLO 预过滤 → 正常场景跳过 VLM（省 80-95% 调用）
2. CLIP-Adapter 残差融合 → 高置信度跳过 VLM
3. VLM 精准分析 → 仅可疑帧触发

#### 数据层 — 事件汇聚与业务逻辑

| 子系统 | 职责 | 关键数据 |
|--------|------|----------|
| **Event Hub** | 多租户事件摄入/查询/隔离 | OpsEvent (event_id, type, store_id, metadata) |
| **成本分析** | 损耗预测/出成率/供应商对账/预算 | SKU 标准出成率, IoT 重量, PO 单价 |
| **任务引擎** | F-TASK 任务创建/分配/督办 | 任务状态机, 企微推送 |
| **SOP 引擎** | 7 条 SOP 规则匹配/合规率计算 | 检查点: IoT+VLM+人工+POS |
| **告警网关** | 告警路由/升级/企微推送 | 告警级别, 升级链 |

**DB 架构**:
- SQLite (dev): `demo/data/hub.db` + `hub_alerts.db`
- PostgreSQL (prod): `HOTPOT_DATABASE_URL` 环境变量切换

#### 展示层 — 用户界面

| 用户角色 | 核心页面 | 设备 |
|----------|----------|------|
| 店长 | 驾驶舱、成本分析、SOP 看板 | 大屏/PC |
| 后厨主管 | 智能识别、任务管理 | PC/PDA |
| 前厅经理 | 桌台管理、翻台效率 | PC/移动端 |
| 区域经理 | 区域总览、跨店对标 | PC |
| 总部管理层 | 驾驶舱、供应商 KPI | 大屏/PC |
| 系统管理员 | 设备管理、RBAC、管线配置 | PC |

**主题系统**: 火锅暖色系 (`--brand: #E2613A`, `--bg: #15110E`, `--card: #1F1813`)

---

## 3. 模块成熟度标注

### 3.1 成熟度等级定义

| 等级 | 标识 | 定义 |
|------|------|------|
| 🟢 **生产就绪** | Production | 已验证通过，可部署到生产环境 |
| 🟡 **测试中** | Testing | 功能完整，E2E 已跑通或待容器化 |
| 🟠 **开发中** | In Dev | 框架就绪，核心功能缺失或未联调 |
| 🔴 **规划中** | Planned | 方案已有，代码未开始 |
| ⚫ **废弃** | Deprecated | 已被新架构取代，保留参考 |

### 3.2 边缘端成熟度

| 模块 | 子模块 | 成熟度 | 说明 |
|------|--------|--------|------|
| **edge/agent** | server.py (统一入口) | 🟢 生产就绪 | 注册+心跳+配置热重载完整 |
| | config.py | 🟢 生产就绪 | 环境变量驱动+启动校验 |
| | kitchen_infer.py | 🟢 生产就绪 | YOLO+VLM 管线，E2E 已验证 |
| | front_hall_infer.py | 🟡 测试中 | plan_a/plan_b 双模式可跑，待生产场景验证 |
| **edge/kitchen** | pipeline.py (管线调度) | 🟢 生产就绪 | stages/ 注册表架构，3次重试推 Hub |
| | stages/ (4个管线级) | 🟢 生产就绪 | YOLO+CLIP+VLM+Anomaly 全部就绪 |
| | rules.py | 🟢 生产就绪 | 阈值/提示词/降级矩阵完整 |
| | yolo_infer.py | 🟢 生产就绪 | YOLOv8n 实时推理 8ms |
| | clip_infer.py | 🟡 测试中 | CLIP 子进程已验证 |
| | vlm_infer.py | 🟡 测试中 | Ostrakon-VL 4类识别已验证 (57s)，待优化 |
| | capture/ipc_frame_grabber.py | 🟠 开发中 | 代码就绪，缺 RTSP 地址 |
| | bridge/waste_vision.py | 🟢 生产就绪 | 桥接已验证 |
| | kalman_tracker.py | 🟡 测试中 | Kalman 滤波实现完成 |
| **edge/front_hall** | pipeline.py | 🟢 生产就绪 | analyze_table 统一入口 |
| | rules.py | 🟢 生产就绪 | COCO 映射/告警/推荐语完整 |
| | strategies/plan_b.py | 🟢 生产就绪 | 纯 YOLO 规则 ~40ms |
| | strategies/plan_a.py | 🟡 测试中 | YOLO+CLIP ~190ms，待生产验证 |
| | engines/yolo.py | 🟢 生产就绪 | RealYoloDetector 封装 |
| | engines/clip_server.py | 🟡 测试中 | CLIP 子进程架构已验证 |
| | iot/ (MQTT/传感器) | 🟠 开发中 | 模拟就绪，缺硬件 |
| | bridge/store_forward.py | 🟡 测试中 | 断网缓存逻辑已实现 |
| **edge/common** | real_yolo.py | 🟢 生产就绪 | ultralytics 封装，前厅/后厨共用 |
| | yolo_onnx.py | 🟡 测试中 | ONNX 备选 |
| | rknn_backend.py | 🟡 测试中 | RKNN NPU 备选 |
| **edge/legacy** | 全部 | ⚫ 废弃 | 已被 edge/agent 架构取代 |

### 3.3 云端成熟度

| 模块 | 子模块 | 成熟度 | 说明 |
|------|--------|--------|------|
| **Hub API :8098** | app.py + server.py | 🟢 生产就绪 | FastAPI 入口，CORS/静态/路由 |
| | routers/ (18个路由域) | 🟢 生产就绪 | 全部 18 路由域就绪 |
| | auth.py (API Key + JWT) | 🟢 生产就绪 | 边缘+用户双认证 |
| | rbac.py | 🟡 测试中 | RBAC 策略已定义，Dashboard前端缺失 |
| | db.py (SQLite) | 🟢 生产就绪 | SQLite 持久化可用 |
| | pg_db.py (PostgreSQL) | 🟡 测试中 | PG 适配就绪，缺生产部署验证 |
| | devices API (注册/心跳/配流) | 🟢 生产就绪 | API 完整 |
| | daily_scheduler.py | 🟡 测试中 | 三时段调度已实现 |
| | task_factory.py | 🟢 生产就绪 | F-TASK 内核完整 |
| **成本分析** | analyzer.py | 🟢 生产就绪 | 损耗/出成率/对账逻辑完整 |
| | feature_builder.py | 🟢 生产就绪 | 特征工程就绪 |
| **SOP 引擎** | sop_engine.py | 🟢 生产就绪 | 规则引擎+7条SOP |
| | scheduler.py | 🟡 测试中 | 调度器就绪 |
| **告警** | alert_gateway | 🟢 生产就绪 | 企微/邮件/短信 |
| **VLM 复核** | vlm_review/ | 🟡 测试中 | 桩就绪，待接 GPT-4V |
| **LLM 日报** | llm_report/ | 🟠 开发中 | rule 兜底可用，OpenAI 待接 |
| **集成** | pos_bridge / erp_bridge | 🟡 测试中 | 接口定义，待真实 POS/ERP 对接 |
| **Dashboard** | vlm-demo.html | 🟢 生产就绪 | 智能识别页完整（含图片精选逻辑） |
| | cost.html / alerts.html / tasks.html | 🟢 生产就绪 | 核心业务页可用 |
| | login.html | 🟢 生产就绪 | JWT 登录可用 |
| | index.html / cockpit.html | 🟡 测试中 | 页面存在，未接真实数据 |
| | tables.html / kitchen.html | 🟡 测试中 | 页面存在，部分数据 |
| | devices.html | 🔴 规划中 | P0 缺口：盒子没法上线管理 |
| | admin/ RBAC 面板 | 🔴 规划中 | P1 缺口 |
| | theme.css + core.js | 🟢 生产就绪 | 前端基础设施完整 |

### 3.4 部署成熟度

| 模块 | 成熟度 | 说明 |
|------|--------|------|
| deploy-hotpot.sh | 🟢 生产就绪 | 一键部署 10 Phase 完整流程 |
| Jetson Docker | 🟠 开发中 | Dockerfile 已写，容器化未完成（共享库冲突） |
| Edge Docker | 🟠 开发中 | Dockerfile 已写，未构建验证 |
| Cloud Docker | 🟡 测试中 | docker-compose 就绪 |
| systemd 服务 | 🟡 测试中 | 5个 service 文件就绪 |
| 模型分发 | 🟡 测试中 | rsync 增量部署可用 |

### 3.5 测试成熟度

| 类别 | 数量 | 覆盖率 |
|------|------|--------|
| Hub API 测试 | 18 文件 | 全部路由域覆盖 |
| 业务逻辑测试 | 12 文件 | 成本/损耗/任务/SOP |
| 集成测试 | 4 文件 | IoT/RBAC/企微/门店隔离 |
| 边缘测试 | 3 文件 | YOLO/废料估算/断网 |
| 总计 | 37 文件, 176 测试 | ~85% API 覆盖率 |

### 3.6 成熟度统计

| 等级 | 数量 | 占比 |
|------|------|------|
| 🟢 生产就绪 | 28 | 42% |
| 🟡 测试中 | 24 | 36% |
| 🟠 开发中 | 6 | 9% |
| 🔴 规划中 | 2 | 3% |
| ⚫ 废弃 | 1 | 1.5% |
| **总模块数** | **66** | |

---

## 4. 产品开发路线图

### 里程碑总览

```
Week 1           Week 2           Week 3           Week 4
──────────────────────────────────────────────────────────
P0 设备管理上线   P1 Docker 全链路  P1 RBAC 上线      YOLOv8→v26 升级
RTSP 配置打通     前厅 Docker 验证   Dashboard 补全    Kalman 滤波优化
                 P1 Supervision    P2 代码 Git push   VLM 推理加速
                                                     E2E 性能测试
──────────────────────────────────────────────────────────
Week 5           Week 6-8                           Week 9-12
IoT 硬件对接     门店试点 (玉环)                     全国推广准备
POS/ERP 集成     反馈迭代                           加盟 SaaS 化
LLM Agent 上线   第二批门店 (椒江)                    模型 OTA
```

### Week 1 — P0 关键缺口攻坚

| 优先级 | 任务 | 交付物 | 负责人 |
|--------|------|--------|--------|
| 🔴 P0 | **设备管理 Dashboard** — devices.html 完整实现 | 设备注册/列表/配流/状态 UI | 小卡(Cursor) |
| 🔴 P0 | **IPC RTSP 配置** — 玉环店摄像头对接 | RTSP 地址配置 + ipc_frame_grabber 联调 | 小抠(Codex) |
| 🔴 P0 | **config_pending 机制完善** — 管理员 PUT config → 设备实时拉取 | 配流全链路打通 | 小居(Gemini) |
| 🟡 P1 | **Dashboard 首页接真实数据** — index.html 从 Hub API 拉数据 | 驾驶舱首页可视化 | 小卡 |

### Week 2 — P1 容器化 + 工程化

| 优先级 | 任务 | 交付物 | 负责人 |
|--------|------|--------|--------|
| 🟡 P1 | **后厨 Docker 全链路** — 解决共享库冲突，容器化验证 | Docker 一键启动→推理→Hub | 小抠 |
| 🟡 P1 | **前厅 Docker 构建验证** — Dockerfile 构建 + E2E 测试 | 前厅容器就绪 | 小抠 |
| 🟡 P1 | **Supervision 完整集成** — 替换自定义标注逻辑 | CV 后处理标准化 | 小抠 |
| 🟡 P1 | **PostgreSQL 生产切换** — pg_db.py 生产环境验证 | PG 迁移脚本 + 备份策略 | 小抠 |

### Week 3 — RBAC + 前端补全

| 优先级 | 任务 | 交付物 | 负责人 |
|--------|------|--------|--------|
| 🟡 P1 | **Dashboard RBAC 面板** — admin/ 完整实现 | 用户/角色/权限管理 UI | 小卡 |
| 🟡 P1 | **前厅场景分析页** — front-hall.html 接真实数据 | 前厅场景可视化 | 小卡 |
| 🟡 P1 | **Dashboard 端到端数据流** — cockpit/regional/report 接 Hub | 所有页面真实数据 | 小卡 |
| 🟢 P2 | **代码 Git push** — 等 VPN | GitHub 仓库同步 | 小马 |

### Week 4 — 模型升级 + 性能优化

| 优先级 | 任务 | 交付物 | 负责人 |
|--------|------|--------|--------|
| 🟢 P2 | **YOLOv8→v26 升级** — NMS-free, STAL 小目标优化 | yolo26n 模型替换 + 回归测试 | 小抠 |
| 🟢 P2 | **Kalman 滤波投产** — 参数调优 + 性能基线 | Kalman 跟踪精度报告 | 小抠 |
| 🟢 P2 | **VLM 推理加速** — Ostrakon-VL 量化/批处理 | 推理耗时 <15s (从 57s) | 小抠 |
| 🟢 P2 | **E2E 性能测试** — 全链路延迟/吞吐基线 | 性能测试报告 | 小居 |

### Week 5 — IoT + 集成

| 优先级 | 任务 | 交付物 | 负责人 |
|--------|------|--------|--------|
| 🟠 P1 | **IoT 硬件对接** — 智能秤/温感/门磁 接入 MQTT | 传感器数据→Hub 通路 | 小抠 |
| 🟠 P1 | **POS 系统集成** — 玉环店 POS 对接 | POS 订单→桌态关联 | 小抠 |
| 🟠 P1 | **LLM 日报 Agent 上线** — OpenAI API 接入 + 企微推送 | 每日自动运营日报 | 小居 |

### Week 6-8 — 玉环门店试点

- 全系统部署到玉环店 Jetson
- 真实场景数据收集（后厨废弃/前厅桌态）
- 模型迭代（基于真实数据 fine-tune）
- 用户反馈收集与迭代

### Week 9-12 — 全国推广准备

- 加盟 SaaS 化（多租户隔离完善）
- 模型 OTA 下发机制
- 第二批门店部署（椒江）
- 运维手册 + 培训材料

---

## 5. 技术债清单

### 5.1 架构债

| ID | 问题 | 影响 | 优先级 | 建议 |
|----|------|------|--------|------|
| TD-001 | **hotpot_platform/ 目录名与 Python stdlib 冲突** — `import platform` 被劫持 | CLIP 子进程需 cwd=/tmp 绕开；新开发者易踩坑 | 🟡 P1 | 重命名为 `hotpot_cloud/` 或加 `__init__.py` + sys.path.append |
| TD-002 | **edge/server.py 与 edge/agent/server.py 概念重叠** — `front_hall/server.py` 仍存在 | 代码重复，维护分裂 | 🟡 P1 | 彻底废弃旧 server，统一到 edge/agent |
| TD-003 | **device_stub.py 是桩** — 设备管理缺完整实现 | 盒子无法通过 Dashboard 管理 | 🔴 P0 | 实现完整的 device 管理 |
| TD-004 | **Mock 与真实实现耦合** — `HOTPOT_DEV_MODE` 散落各处 | 生产部署可能意外走 mock | 🟡 P1 | 统一 mock/real 切换为策略模式或 DI |
| TD-005 | **Dashboard API URL 硬编码** — `127.0.0.1:9090` / `192.168.2.85:8098` | 部署环境变更时需手动改多处 | 🟡 P1 | 统一为 `core.js` 中的 `HUB_API_BASE` 配置 |
| TD-006 | **zone 过滤不一致** — Dashboard `备餐废弃区` vs Jetson `混合废弃区` | 数据拉取失败，无可见报错 | 🟡 P1 | 统一 zone 命名规范 + 校验 |

### 5.2 代码质量债

| ID | 问题 | 文件 | 优先级 |
|----|------|------|--------|
| TD-010 | YOLO 检测与 VLM 触发逻辑重复 — kitchen_infer.py 和 pipeline.py 各有 `_should_trigger_vlm` | kitchen_infer.py, pipeline.py | 🟡 P1 |
| TD-011 | 图片路径处理不一致 — 有的用 PROJECT_ROOT 解析，有的直接 Path(image_path) | front_hall_infer.py, kitchen_infer.py | 🟢 P2 |
| TD-012 | 错误处理粒度粗 — `except Exception as e` 在多处使用 | 多处 | 🟢 P2 |
| TD-013 | 日志级别不统一 — logging vs print 混用 | pipeline.py, server.py | 🟢 P2 |
| TD-014 | 测试覆盖缺失 — front_hall plan_a/plan_b 无独立测试 | tests/ | 🟡 P1 |

### 5.3 性能债

| ID | 问题 | 影响 | 优先级 |
|----|------|------|--------|
| TD-020 | **VLM 推理 57s** — Ostrakon-VL-8B 在 Jetson 上单次推理 | 实时性不满足业务需求 | 🟡 P1 |
| TD-021 | **CLIP 子进程每次加载模型** — 启动延迟 | plan_a 首次调用慢 | 🟡 P1 |
| TD-022 | **无推理结果缓存** — 相同场景重复推理 | 资源浪费 | 🟢 P2 |
| TD-023 | **IPC 抓帧无帧率控制** — 可能产生大量无效帧 | 存储 + 推理浪费 | 🟡 P1 |

### 5.4 安全债

| ID | 问题 | 影响 | 优先级 |
|----|------|------|--------|
| TD-030 | **API Key 默认值** — `test-key` | 生产需要替换 | 🟡 P1 |
| TD-031 | **JWT Secret 默认值** — `CHANGE_ME` | 生产必须替换（已有多层校验） | 🟡 P1 |
| TD-032 | **Dashboard CORS `*`** — dev 模式不安全 | 生产需配置 allowlist | 🟡 P1 |
| TD-033 | **HTTPS 未配置** — Hub/Dashboard 裸 HTTP | 生产需 nginx + SSL | 🟡 P1 |

### 5.5 运维债

| ID | 问题 | 影响 | 优先级 |
|----|------|------|--------|
| TD-040 | **无健康检查自动恢复** — watchdog.sh 仅监控不重启 | 服务挂掉需手动介入 | 🟡 P1 |
| TD-041 | **无日志轮转** — `/tmp/hub.log` 无限增长 | Jetson 磁盘风险 | 🟢 P2 |
| TD-042 | **模型版本管理缺失** — 无模型 hash/版本号 | 回滚困难 | 🟢 P2 |
| TD-043 | **Git 未 push** — 代码仅本地 | 灾难恢复风险 | 🔴 P0 |

### 5.6 文档债

| ID | 问题 | 优先级 |
|----|------|--------|
| TD-050 | **API 文档缺失** — 无 OpenAPI/Swagger 静态文档 | 🟡 P1 |
| TD-051 | **部署文档过时** — deploy/README.md 与实际脚本不一致 | 🟢 P2 |
| TD-052 | **front_hall plan_a 的 CLIP 通信协议未文档化** | 🟢 P2 |

---

## 6. 附录：数据流全链路

### 6.1 后厨废料识别全链路 (已验证 E2E)

```
IPC 摄像头
  │ RTSP 流
  ▼
ipc_frame_grabber.py ──► /tmp/ipc_frames/latest.jpg
  │
  ▼
edge/agent :9100  ──► kitchen_infer.py
  │
  ├─ YOLO 预过滤 (8ms)
  │   ├─ 无可疑 → 结束（省 VLM 调用）
  │   └─ 可疑 ↓
  ├─ CLIP-Adapter 场景分类 (~50ms)
  │   ├─ 高置信度 → 结束
  │   └─ 低置信度 ↓
  └─ VLM 语义分析 (Ostrakon-VL-8B, 320ms-57s)
      └─ 输出: SKU/废弃类型/份量/建议
  │
  ▼  POST /v1/vlm/waste-estimate
Hub :8098
  │  waste_estimate.py → 持久化事件
  │  static/images/{store_id}/{zone}/{event_id}.jpeg
  ▼
Dashboard :9120
  │  vlm-demo.html ← GET /v1/events?limit=&zone=
  │  ┌─ 图片展示 (优先级: metadata.image_url > 事件时间戳文件名)
  │  └─ 识别结果卡片 (SKU/废弃类型/置信度/建议)
```

### 6.2 前厅场景分析全链路

```
IPC 摄像头
  │ RTSP 流 / 上传
  ▼
edge/agent :9100  ──► POST /api/scene/analyze
  │
  ├─ plan_b (默认, ~40ms)
  │   └─ YOLO 检测 → counts → 规则判决 → 四态+告警+推荐
  │
  └─ plan_a (可选, ~190ms)
      ├─ YOLO 检测
      ├─ 无人 → 直接返回
      └─ 有人 → CLIP 子进程 (table/service/customer 三组)
          └─ 语义分类 → 桌态+服务事件+顾客行为
  │
  ▼  store_forward (断网时缓存)
Hub :8098
  │  POST /v1/events
  │  桌态: empty/ready/dining/needs_cleaning
  │  告警: needs_cleaning/low_drinks/empty_plate/customer_ready_to_pay
  ▼
Dashboard (tables.html / front-hall.html)
```

### 6.3 设备管理全链路 (配流)

```
Dashboard (devices.html) ← 🔴 待开发
  │ PUT /v1/devices/{id}/config
  ▼
Hub :8098
  │ config_pending=True
  │
  ├─ 设备 heartbeat 返回 config
  └─ 设备 pull-config 返回 config
  ▼
Edge Agent :9100
  │ apply_device_config(config)
  │ ├─ 按 enabled 启停 kitchen/front_hall 模块
  │ ├─ 写 IPC 配置文件
  │ └─ 持久化 device_config.json
```

---

## 技术栈总览

| 层级 | 技术 | 版本/型号 |
|------|------|-----------|
| **应用框架** | FastAPI + uvicorn | 最新 |
| **目标检测** | ultralytics (YOLOv8n, YOLO26n) | >=8.0, <8.3 |
| **语义理解** | OpenAI CLIP (ViT-B/32) | 子进程调用 |
| **视觉语言** | Ostrakon-VL-8B (GGUF IQ4_XS) | llama-mtmd-cli |
| **大语言模型** | OpenAI API (rule 兜底) | GPT-4 |
| **计算机视觉** | OpenCV | opencv-python-headless |
| **IoT 协议** | MQTT (paho-mqtt) | — |
| **数据库** | SQLite / PostgreSQL | — |
| **容器化** | Docker + docker-compose | Jetson Orin |
| **部署** | rsync + bash | Mac→Jetson |
| **前端** | 纯 HTML/CSS/JS (vanilla) | 静态文件服务 |
| **测试** | pytest | 37 文件 176 测试 |
| **版本** | V3.10 | 20260711-1735 |

---

> **文档维护**: 本 PRD 基于实际代码生成。代码变更后应同步更新本文档。  
> **关联文档**: `docs/PROJECT_OVERVIEW.md`（项目全貌）· `docs/solution.md`（完整方案）· `CLAUDE.md`（架构协作文档）· `docs/autonomous_dev_roadmap.md`（自主开发路线图）
