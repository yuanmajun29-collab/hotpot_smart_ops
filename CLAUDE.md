# Project context for Claude Code

This file is auto-loaded by Claude Code. The section below is updated by Agent Coordinator when you run `coordinator context inject`.

## Shared state (Agent Coordinator)


---
SHARED PROJECT STATE (from other AI tools):
---

Current State:
- CODEX_REVIEW_CLAUDE_LOSS_BUDGET_SOLUTION: ✅ 已收敛。kitchen_loss_budget_solution.md 降级为 SSOT 从属执行附录，硬件口径/编号/持久化全部对齐 ADR-019。

Recent Decisions:
- hermes: 前厅场景分析双模式落地（plan_b YOLO规则 40ms + plan_a YOLO+CLIP混合 ~190ms）
- hermes: Edge 服务器必须从 /tmp 启动绕开 hotpot_platform/ 目录污染

---
IMPORTANT: Before making changes that affect these values, coordinate with other tools.
If you change any of these, declare it using: declareStateChange(key, oldValue, newValue)
---


## 项目架构

```
hotpot_smart_ops/
├── deploy/             # 部署（源码端 → 板端）
│   ├── jetson/         #   Jetson 板端：deploy.sh + build.sh
│   ├── cloud/          #   云端：docker compose
│   └── bridge/         #   VLM→Hub 桥接
├── hotpot_platform/    # 云平台（Hub + Dashboard）
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
    "front_hall": {"enabled": false, "cameras": [], "inference_interval": 30, "rules": {}}
  }
}
```