# AR-401 会前材料 · 代码目录映射

**design_dev §2.5 vs 仓库现状 · 一页速查**

| 项目 | 内容 |
|------|------|
| 用途 | AR-401 会前 · 研发负责人交付 |
| 关联 | [design_dev_implementation_plan.md §2.5](design_dev_implementation_plan.md#25-代码仓库与模块映射) · [architecture_design_phase1.md §2.3](architecture_design_phase1.md#23-代码映射) |
| 更新 | 2026-06-15 |
| 分支 | `release/pilot` / `main` |

---

## 1. 目录树对照

| design_dev §2.5 规划 | 仓库现状 | 对齐 | 说明 |
|----------------------|----------|:----:|------|
| `shared/` | `shared/`（5 文件） | ✅ | schemas · hub_client · iot_sensors · store_config |
| `edge/detector/` | `edge/detector/` | ✅ | mock / yolo_onnx / rknn_backend |
| `edge/ingest/` | **`edge/stream/`** | ⚠️ 更名 | `sources.py` = VideoIngest；`vision_worker.py` = 周期推理 |
| `edge/iot/`（生产） | **未建** | ❌ | 现用 `edge/iot_mock/`；BL-02 需新建或升格 |
| `edge/iot_mock/` | `edge/iot_mock/`（3 文件） | ✅ PoC | mqtt_bridge · sensor_simulator · ingredient_iot_bridge |
| `edge/rknn_deploy/` | `edge/rknn_deploy/` | ⚠️ | prepare_rknn + output 样例；未接入主流程 |
| `edge/queue/`（ADR-008） | **未建** | ❌ | DEV-105 离线 24h |
| `cloud/event_hub/` | `cloud/event_hub/`（8 文件） | ✅ | app · db · pg_db · auth · hub_core |
| `cloud/sop/` | `cloud/sop/` | ✅ | sop_engine · scheduler |
| `cloud/cost_control/` | `cloud/cost_control/` | ⚠️ | analyzer 有；逻辑部分在 Hub `/cost` |
| `cloud/llm_report/` | `cloud/llm_report/` | ⚠️ | report_agent · sop_rag；日报定时未接 |
| `cloud/vlm_review/` | `cloud/vlm_review/` | ⚠️ | app + server；docker profile vlm |
| `cloud/alert/` | **`cloud/alert_gateway/`** | ⚠️ 更名 | gateway.py；企微 webhook 可选 |
| `cloud/config/` | **未建** | — | Phase 2 配置中心 |
| `integrations/`（根） | **`cloud/integrations/`** | ⚠️ 位置 | pos_bridge · erp_bridge |
| `dashboard/` | `dashboard/`（13 HTML + assets） | ✅ | 静态 HTML，非 TS 生产前端 |
| `deploy/` | `deploy/systemd/` + `deploy/uat/` | ✅ | 5 个 systemd 单元；两店 UAT 包 |
| `tests/` | `tests/`（5 文件 + conftest） | ✅ | hub · erp · pos · vlm · sop_rag · **20 项** |
| — | `demo/` | ➕ PoC | run_poc · run_store_pipeline · seed 数据 |
| — | `scripts/` | ➕ 工具 | ROI 标定 · edge_health · 训练导出 |
| — | `models/` | ➕ 模型 | ONNX/RKNN 权重占位 |

**结论**：核心 L1/L2 路径 **80% 对齐**；差异主要为 **命名/位置**（`stream`↔`ingest`、`alert_gateway`↔`alert`、integrations 在 `cloud/` 下）及 **3 项未建**（`edge/iot/`、`edge/queue/`、`cloud/config/`）。

---

## 2. 设计模块 → 代码文件（Phase 1）

| 设计模块 | 主文件 | 闭环 | 真数据 |
|----------|--------|------|:------:|
| VideoIngest | `edge/stream/sources.py` | C-01 | ❌ 默认图片 |
| TableDetector | `edge/detector/hotpot_detector.py` | C-01 | ❌ mock 默认 |
| VisionWorker | `edge/stream/vision_worker.py` | C-01 | ⚠️ 5s 周期写 live JSON |
| IoTAgent | `edge/iot_mock/mqtt_bridge.py` | C-02 C-03 | ❌ sim |
| IngredientBridge | `edge/iot_mock/ingredient_iot_bridge.py` | C-03 C-05 | ⚠️ demo |
| OpsEvent 模型 | `shared/schemas.py` | 全 | ✅ |
| HubClient | `shared/hub_client.py` | 全 | ✅ POST /events |
| Event Hub API | `cloud/event_hub/app.py`（组装根 112 行）+ `routers/*.py`（10 域）+ `runtime.py` + `rbac.py` + `domain/` | 全 | ✅ 50 路由 + 24 /v1 别名 |
| 持久化 | `cloud/event_hub/db.py` · `pg_db.py` | 全 | ⚠️ SQLite 默认 |
| SOP Engine | `cloud/sop/sop_engine.py` | C-04 | ⚠️ seed |
| SOP Scheduler | `cloud/sop/scheduler.py` | C-04 | ⚠️ |
| Alert Gateway | `cloud/alert_gateway/gateway.py` | C-02 C-05 | ⚠️ 文件 mock |
| 成本分析 | `cloud/cost_control/analyzer.py` | C-05 | ⚠️ |
| POS Bridge | `cloud/integrations/pos_bridge.py` | C-01 | ⚠️ sim |
| ERP Bridge | `cloud/integrations/erp_bridge.py` | C-05 | ⚠️ mock PO |
| VLM Review | `cloud/vlm_review/app.py` | C-05 PDA | ⚠️ stub |
| LLM / RAG | `cloud/llm_report/report_agent.py` · `sop_rag.py` | C-04 C-06 | ⚠️ rule |
| 看板鉴权 | `cloud/event_hub/auth.py` | 全 | ⚠️ demo JWT |
| 看板 UI | `dashboard/*.html` · `assets/core.js` | 全 | ✅ 15 页 |

---

## 3. 六闭环 C-01~C06 · 代码路径

| ID | 场景 | 边缘/集成 | Hub 接口 | 看板页 | 断点 |
|----|------|-----------|----------|--------|------|
| C-01 | 翻台 | vision_worker → detector | GET `/tables` `/summary` · POST `/events` | `tables.html` | 真 RTSP+yolo（BL-01） |
| C-02 | 后厨合规 | mqtt_bridge · CV | GET `/alerts/*` · POST `/events` | `kitchen.html` `alerts.html` | 真 IoT（BL-02） |
| C-03 | 食材全链路 | ingredient_iot_bridge | GET `/iot` · POST `/iot` | `kitchen.html` | MQTT 真传感器 |
| C-04 | SOP | seed signals → sop_engine | GET `/sop` · POST `/sop/ask` | `sop.html` | 真违规检测 |
| C-05 | 来料成本 | erp_bridge · 秤 | GET `/cost` `/erp` | `cost.html` `pda/` | 真 ERP+签字（BL-04/05） |
| C-06 | 日报 | report_agent | 前端 buildReport | `report.html` | 22:00 定时（BL-06） |

**数据种子**：`demo/data/stores/{store_yuhuan|store_jiaojiang}/` · 流水线 `demo/run_store_pipeline.sh`

---

## 4. Hub API 与模块归属

```
cloud/event_hub/app.py          ← 组装根（runtime.init + lifespan + include_router×10）
  ├─ routers/*.py               ← 10 业务域路由（system/auth/ingest/receiving/sop/iot/reports/alerts/org/admin）
  ├─ runtime.py                 ← 单例容器（hub/db/alert_gateway/org_registry 延迟绑定）
  ├─ rbac.py                    ← RolePolicy 集中式权限（auth.py 委托）
  ├─ domain/                    ← health / turnover 纯函数
  ├─ auth.py                    ← POST /auth/token（运行时 auth_mode）
  ├─ hub_core.py                ← summary / tables / sop 聚合
  ├─ db.py | pg_db.py           ← events · store_snapshots
  └─ 调用 alert_gateway.gateway ← 告警推送

待实现（architecture_api_spec · sprint §6.1）：
  POST /v1/sop/assign           ← BL-05（DEV-421）
  APScheduler 22:00 日报        ← BL-06

已实现（BL-05）：
  POST /v1/receiving/submit · GET /v1/receiving/batches
  GET  /v1/audit/signatures · GET /v1/audit/acks
  POST /v1/sop/assign · GET /v1/sop/assignments

BL-01 脚本：scripts/enable_pilot_cv.sh（RTSP + yolo 切换）
BL-02 打桩：scripts/run_iot_stub.sh + edge/iot_mock/iot_stub_bridge.py（无设备）
```

---

## 5. 差异汇总与 DEV 映射

| # | 差异 | 影响 | 建议 | DEV |
|---|------|------|------|-----|
| D1 | `edge/iot/` 未建 | 生产 IoT 与 mock 混用 | Phase 1 升格 `iot_mock`→`iot` 或保留 mock+真 MQTT 双轨 | BL-02 |
| D2 | `edge/queue/` 未建 | 断网 24h 未兑现 | SQLite 边缘队列 + bulk POST | DEV-105 |
| ~~D3~~ | ✅ 已解决（2026-06-18） | /v1 别名 + Deprecation 头全量落地 | — | ADR-004 已采纳 |
| D4 | CV 默认 mock | C-01 无真桌态 | `HOTPOT_DETECTOR_BACKEND=yolo` | DEV-408~410 |
| D5 | 签字/审计表未建 | C-05 不合规 | receiving_signatures + audit API | BL-05 |
| D6 | RBAC 宽松 | 店级隔离弱 | JWT claims 强制 store_id | BL-07 |
| D7 | `cloud/config/` 无 | SOP OTA 延后 | Phase 2，不阻塞试点 | — |
| D8 | 测试 5 文件 | 覆盖率不足 | BL 专项补集成测试 | 各 BL |

---

## 6. AR-401 现场勾选（快速）

| 问题 | 建议结论 |
|------|----------|
| 目录差异 D1~D8 是否接受为 Phase 1 已知差距？ | ☐ 是 |
| `edge/stream` 是否正式等同 design `edge/ingest`？ | ☐ 是（文档同步） |
| `cloud/integrations` 是否保持现路径（不迁根目录）？ | ☐ 是 |
| PoC 保留 `demo/` + `iot_mock/` 用于 CI？ | ☐ 是（ADR 补充） |

---

## 7. 会前自检命令

```bash
cd /mnt/project/hotpot_smart_ops
pytest -q                                    # 20 passed（tests/conftest.py 已配置路径）
curl -s http://127.0.0.1:8088/health         # Hub（需先 docker compose up -d）
python3 scripts/edge_health.py --store-id store_yuhuan --hub-url http://127.0.0.1:8088
```

---

**会后**：若确认 D1/D2 路径，更新 design_dev §2.5 脚注或 ADR；差异关闭项写入 [architecture_review_outcome_template.md](architecture_review_outcome_template.md)。
