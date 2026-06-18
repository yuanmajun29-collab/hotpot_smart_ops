# 冯校长火锅 · 智能运营 PoC

**冯校长火锅**全国连锁场景：**LLM + VLM + 视频监测 + IoT + 边缘计算**。

**Phase 1 试点店（台州）**

| store_id | 店名 |
|----------|------|
| `store_yuhuan` | 冯校长火锅·玉环店 |
| `store_jiaojiang` | 冯校长火锅·椒江店 |

门店配置见 [`demo/data/stores.json`](demo/data/stores.json)。登录看板时可切换门店；Hub 已支持 **多租户**，两店数据相互隔离。

```bash
# 查看已注册门店
curl http://127.0.0.1:8088/stores

# 按门店查询摘要
curl "http://127.0.0.1:8088/summary?store_id=store_yuhuan"
curl "http://127.0.0.1:8088/summary?store_id=store_jiaojiang"

# 区域跨店对标（F-HQ01）
curl http://127.0.0.1:8088/benchmark
```

## 完整方案文档

**产品设计（入口）** → **[docs/product_design_index.md](docs/product_design_index.md)** — 文档索引与阶段 DoD

| 类型 | 文档 |
|------|------|
| 目标 | [product_goal_card.md](docs/product_goal_card.md) — 一页目标卡 |
| 切入口 | [kitchen_loss_prediction_wedge_plan.md](docs/kitchen_loss_prediction_wedge_plan.md) — 后厨损耗预测先证明 ROI |
| PRD | [product_design.md](docs/product_design.md) — 产品设计规格 V1.6 |
| 故事 | [user_story_map.md](docs/user_story_map.md) — 用户故事地图 |
| 界面 | [figma_component_spec.md](docs/figma_component_spec.md) — 组件与 Frame |
| 推送 | [push_notification_templates.md](docs/push_notification_templates.md) — 企微文案 |
| 验收 | [phase1_mvp_acceptance_checklist.md](docs/phase1_mvp_acceptance_checklist.md) — MVP 勾选表 |
| 测试 | [test_cases_phase1.md](docs/test_cases_phase1.md) — 全产品测试用例 + F-xxx 追溯（93 passed） |
| 评审 | [product_review_checklist.md](docs/product_review_checklist.md) — PM-401 |
| 评审结论回填 | [pm401_review_outcome_template.md](docs/pm401_review_outcome_template.md) — 通过/有条件通过 |
| 邀请 | [pm401_meeting_invite_template.md](docs/pm401_meeting_invite_template.md) — 模板 |
| 邀请定稿 | [pm401_meeting_invite_20260617.md](docs/pm401_meeting_invite_20260617.md) — **6/17 14:00** |
| 议程 PDF | [pm401_meeting_agenda_20260617.html](docs/pm401_meeting_agenda_20260617.html) — 打印/导出 PDF |
| PM-402 邀请 | [pm402_meeting_invite_20260619_20.md](docs/pm402_meeting_invite_20260619_20.md) — **6/19·6/20** |
| 日历 ICS | [product_meetings_phase1.ics](docs/product_meetings_phase1.ics) — 含腾讯会议 888-888-888 |
| 腾讯会议配置 | [product_meetings_tencent.md](docs/product_meetings_tencent.md) — 替换真实会议号 |
| UAT | [uat_concept_test_record.md](docs/uat_concept_test_record.md) — PM-402 |
| 变更 | [product_design_changelog.md](docs/product_design_changelog.md) |

**架构设计（Phase 1）**

| 文档 | 用途 |
|------|------|
| [architecture_design_index.md](docs/architecture_design_index.md) | 索引 · DoD · **AR-401 入口** |
| [architecture_design_phase1.md](docs/architecture_design_phase1.md) | Phase 1 架构规格 |
| [architecture_api_spec.md](docs/architecture_api_spec.md) | REST API + /v1 规划 |
| [architecture_data_model_phase1.md](docs/architecture_data_model_phase1.md) | OpsEvent · 表结构 |
| [architecture_deployment_phase1.md](docs/architecture_deployment_phase1.md) | docker · systemd · 两店 |
| [architecture_decisions.md](docs/architecture_decisions.md) | ADR-001~016 |
| [architecture_review_checklist.md](docs/architecture_review_checklist.md) | AR-401 评审清单 |
| [ar401_code_directory_mapping.md](docs/ar401_code_directory_mapping.md) | **会前必读** · 代码目录映射 |
| [ar401_meeting_invite_20260618.md](docs/ar401_meeting_invite_20260618.md) | **6/18 10:00** 邀请定稿 |
| [ar401_meeting_agenda_20260618.html](docs/ar401_meeting_agenda_20260618.html) | 可打印议程 |
| [architecture_review_outcome_template.md](docs/architecture_review_outcome_template.md) | 会后回填 |
| [architecture_changelog.md](docs/architecture_changelog.md) | 架构变更日志 |

**方案与实施**
- **[docs/solution.md](docs/solution.md)** — V2.0 完整方案（17 章）
- **[docs/design_dev_implementation_plan.md](docs/design_dev_implementation_plan.md)** — 设计 · 开发 · 实施方案（主计划）
- **[docs/executive_summary_onepager.md](docs/executive_summary_onepager.md)** — 决策层一页纸
- **[docs/sprint_task_backlog.md](docs/sprint_task_backlog.md)** — Sprint 1~4 任务（含 §6.1 UAT 阻塞专项）
- **[docs/pilot_deployment_checklist.md](docs/pilot_deployment_checklist.md)** — 试点部署清单索引
  - [直营店清单](docs/pilot_deployment_checklist_direct.md)
  - [加盟店清单](docs/pilot_deployment_checklist_franchise.md)
- **[docs/poc_to_production_gap.md](docs/poc_to_production_gap.md)** — PoC → 生产差距清单

## 快速开始

```bash
cd hotpot_smart_ops
chmod +x demo/run_poc.sh demo/run_store_pipeline.sh demo/run_vision_daemon.sh
./demo/run_poc.sh   # 两店实时流水线 + 后台 vision worker（默认每 5s 扫描桌态）
# VISION_INTERVAL=10 VISION_DAEMON=0 ./demo/run_poc.sh  # 可调间隔或关闭 daemon
```

### Docker Compose 部署（DEV-103）

```bash
docker compose up -d                              # Hub :8088 + 看板 :3000
docker compose --profile postgres up -d           # 附加 PostgreSQL :5432
docker compose --profile iot up -d                # 附加 Mosquitto MQTT
docker compose --profile vlm up -d                # 附加 VLM 服务 :8089
```

PostgreSQL 模式：

```bash
export HOTPOT_DATABASE_URL=postgresql://hotpot:hotpot_dev@localhost:5432/hotpot_ops
docker compose --profile postgres up -d
# 或参考 deploy/.env.postgres.example
```

### 运行指标与健康检查

```bash
curl http://127.0.0.1:8088/health
curl http://127.0.0.1:8088/metrics
```

看板 **系统状态** 页：http://127.0.0.1:3000/system.html

## 目录结构

```
hotpot_smart_ops/
├── docs/solution.md          # 完整解决方案文档
├── edge/detector/            # 边缘视觉检测（桌态/后厨合规）
├── edge/rknn_deploy/         # RKNN 部署脚本
├── edge/iot_mock/            # 环境 IoT + 食材全链路 bridge
│   ├── sensor_simulator.py
│   ├── ingredient_iot_bridge.py
│   └── mqtt_bridge.py        # MQTT → Hub（DEV-205）
├── scripts/calibrate_roi.py  # 桌位 ROI 标定 CLI（DEV-203）
├── tests/                    # Hub 冒烟测试（DEV-107）
├── cloud/integrations/       # POS 等外部系统对接
├── deploy/systemd/             # systemd 服务单元（DEV-104）
├── .gitlab-ci.yml            # CI 流水线
├── cloud/event_hub/          # 事件汇聚 API
├── cloud/sop/                # 后厨 SOP 合规引擎
├── cloud/cost_control/       # 来料成本控制分析
├── cloud/llm_report/         # LLM 运营日报 Agent
├── dashboard/                # Web 运营看板
└── demo/                     # 演示脚本与模拟数据
```

## 单独运行模块

```bash
# 事件汇聚（FastAPI 多租户 + SQLite 持久化，默认 8088）
python3 cloud/event_hub/server.py --port 8088 --seed-dir demo/data/stores
# 旧版 stdlib：python3 cloud/event_hub/server.py --legacy --port 8088

# 边缘检测（可加载 UAT ROI）
python3 edge/detector/hotpot_detector.py --image demo/data/front_hall.jpg --zone front --hub-url http://127.0.0.1:8088

# 边缘视觉 worker（DEV-203 文件模拟流 + UAT ROI + 离线队列，无需真实摄像头）
python3 edge/stream/vision_worker.py --store-id store_yuhuan --hub-url http://127.0.0.1:8088 \
  --output-dir demo/data/stores/store_yuhuan/live

# 周期扫描（每 5 秒一轮，持续运行；Ctrl+C 停止）
python3 edge/stream/vision_worker.py --store-id store_yuhuan --hub-url http://127.0.0.1:8088 \
  --output-dir demo/data/stores/store_yuhuan/live --interval 5 --cycles 0

# 两店后台周期 worker
bash demo/run_vision_daemon.sh http://127.0.0.1:8088 5
bash demo/run_vision_daemon.sh --stop

# IoT 模拟
python3 edge/iot_mock/sensor_simulator.py --hub-url http://127.0.0.1:8088 --inject-anomaly

# IoT 打桩（无需 MQTT / 真设备，BL-02）
./scripts/run_iot_stub.sh                  # 两店 normal，30s 周期
./scripts/run_iot_stub.sh door_alert       # 门磁超时演示（15s 阈值）
./scripts/run_iot_stub.sh --stop

# MQTT 桥接（真设备接入后使用）
python3 edge/iot_mock/mqtt_bridge.py --store-id store_yuhuan --hub-url http://127.0.0.1:8088
python3 edge/iot_mock/mqtt_bridge.py --store-id store_yuhuan --mock-publish  # 向 broker 发模拟数据

# RTSP 模式（UAT config stream_mode=rtsp；无摄像头时自动回退静态图）
HOTPOT_RTSP_ENABLED=1 python3 edge/stream/vision_worker.py --store-id store_yuhuan --hub-url http://127.0.0.1:8088

# BL-01 试点真 CV 一键切换（RTSP + yolo，改 deploy/uat 配置并重启 daemon）
./scripts/enable_pilot_cv.sh pilot yolo    # 启用
./scripts/enable_pilot_cv.sh demo mock   # 回退演示模式

# YOLO/ONNX 模型推理（需 models/table_state.onnx，见 models/README.md）
python3 edge/stream/vision_worker.py --backend yolo --store-id store_yuhuan --hub-url http://127.0.0.1:8088
python3 scripts/export_demo_onnx.py   # 生成 demo ONNX 用于联调

# VLM 复核服务（来料质检 / 清台就绪 / 事件复核）
python3 cloud/vlm_review/server.py --port 8089
curl -X POST http://127.0.0.1:8089/quality-grade -H 'Content-Type: application/json' -d '{"sku":"毛肚","batch_id":"B001"}'

# SOP 智能问答（RAG）
curl -X POST http://127.0.0.1:8088/sop/ask -H 'Content-Type: application/json' -d '{"question":"冷库温度怎么检查"}'

# ERP/供应链 PO 同步（DEV-305）
python3 cloud/integrations/erp_bridge.py --store-id store_yuhuan --hub-url http://127.0.0.1:8088
curl http://127.0.0.1:8088/erp?store_id=store_yuhuan

# POS 数据同步（DEV-304）
python3 cloud/integrations/pos_bridge.py --store-id store_yuhuan --hub-url http://127.0.0.1:8088 --mode sim
curl http://127.0.0.1:8088/pos?store_id=store_yuhuan

# RTSP 探活（试点店摄像头）
python3 scripts/rtsp_probe.py --store-id store_yuhuan

# 桌态模型训练流水线（DEV-201/202）
python3 scripts/build_table_dataset.py --store-id store_yuhuan --auto-label mock
pip install ultralytics && python3 scripts/train_table_classifier.py --epochs 20 --export-onnx

# RKNN 边缘推理（需 RK3588 + .rknn 模型，否则回退 yolo/mock）
python3 edge/stream/vision_worker.py --backend rknn --store-id store_yuhuan --hub-url http://127.0.0.1:8088

# 边缘健康检查
python3 scripts/edge_health.py --store-id store_yuhuan

# 桌位 ROI 标定
python3 scripts/calibrate_roi.py --store-id store_yuhuan list
python3 scripts/calibrate_roi.py --store-id store_yuhuan set --table T01 --bbox 100,200,400,500

# SOP 定时调度（DEV-307）
python3 cloud/sop/scheduler.py --store-id store_yuhuan --once
python3 cloud/sop/scheduler.py --store-id store_yuhuan --interval 3600

# 食材全链路 IoT（来料→保存→加工，驱动 SOP + 成本）
python3 edge/iot_mock/ingredient_iot_bridge.py \
  --input demo/data/ingredient_lifecycle_iot.json \
  --hub-url http://127.0.0.1:8088 \
  --merge-sop-signals demo/data/sop_signals_noon.json

# 后厨 SOP（IoT 信号已 merge 到 sop_signals_noon.json）
python3 cloud/sop/sop_engine.py --shift noon --signals-file demo/data/sop_signals_noon.json --hub-url http://127.0.0.1:8088

# 来料成本（融合 IoT 秤重）
python3 cloud/cost_control/analyzer.py --input demo/data/incoming_materials.json --iot-enrichments demo/data/iot_lifecycle_result.json --hub-url http://127.0.0.1:8088

# LLM 日报（rule 模式无需 API Key）
python3 cloud/llm_report/report_agent.py --hub-url http://127.0.0.1:8088

# 看板（MVP 多页原型 · 概念测试）
python3 dashboard/serve.py --port 3000
# 浏览器打开 http://127.0.0.1:3000/login.html（任意密码登录）
# 系统状态 → http://127.0.0.1:3000/system.html
# 区域督导 → http://127.0.0.1:3000/regional.html（跨店对标）
# 手机 H5：http://127.0.0.1:3000/mobile/index.html 或登录页选「手机版」
# 旧版单页 PoC：http://127.0.0.1:3000/poc.html
```

## 依赖

```bash
python3 -m pip install -r requirements.txt
pytest tests/ -v   # 冒烟测试
```

可选：设置 `OPENAI_API_KEY` 使用 LLM API 后端。

## RKNN 边缘部署

```bash
python3 edge/rknn_deploy/prepare_rknn.py --copy-scripts
```

详见 `edge/rknn_deploy/output/DEPLOY_README.txt`。
