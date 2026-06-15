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

- **[docs/solution.md](docs/solution.md)** — V2.0 完整方案（17 章）
- **[docs/product_design.md](docs/product_design.md)** — 产品设计文档（PRD）
- **[docs/user_story_map.md](docs/user_story_map.md)** — 用户故事地图
- **[docs/figma_component_spec.md](docs/figma_component_spec.md)** — Figma 组件清单
- **[docs/design_dev_implementation_plan.md](docs/design_dev_implementation_plan.md)** — 设计 · 开发 · 实施方案（主计划）
- **[docs/executive_summary_onepager.md](docs/executive_summary_onepager.md)** — 决策层一页纸
- **[docs/sprint_task_backlog.md](docs/sprint_task_backlog.md)** — Sprint 1~4 任务（Jira/Linear 模板）
- **[docs/pilot_deployment_checklist.md](docs/pilot_deployment_checklist.md)** — 试点部署清单索引
  - [直营店清单](docs/pilot_deployment_checklist_direct.md)
  - [加盟店清单](docs/pilot_deployment_checklist_franchise.md)
- **[docs/poc_to_production_gap.md](docs/poc_to_production_gap.md)** — PoC → 生产差距清单

## 快速开始

```bash
cd /home/liuwz/hotpot_smart_ops
chmod +x demo/run_poc.sh demo/run_store_pipeline.sh demo/run_vision_daemon.sh
./demo/run_poc.sh   # 两店实时流水线 + 后台 vision worker（默认每 5s 扫描桌态）
# VISION_INTERVAL=10 VISION_DAEMON=0 ./demo/run_poc.sh  # 可调间隔或关闭 daemon
```

## 目录结构

```
hotpot_smart_ops/
├── docs/solution.md          # 完整解决方案文档
├── edge/detector/            # 边缘视觉检测（桌态/后厨合规）
├── edge/rknn_deploy/         # RKNN 部署脚本
├── edge/iot_mock/            # 环境 IoT + 食材全链路 bridge
│   ├── sensor_simulator.py
│   └── ingredient_iot_bridge.py
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
# 区域督导 → http://127.0.0.1:3000/regional.html（跨店对标）
# 手机 H5：http://127.0.0.1:3000/mobile/index.html 或登录页选「手机版」
# 旧版单页 PoC：http://127.0.0.1:3000/poc.html
```

## 依赖

```bash
pip install -r requirements.txt
```

可选：设置 `OPENAI_API_KEY` 使用 LLM API 后端。

## RKNN 边缘部署

```bash
python3 edge/rknn_deploy/prepare_rknn.py --copy-scripts
```

详见 `edge/rknn_deploy/output/DEPLOY_README.txt`。
