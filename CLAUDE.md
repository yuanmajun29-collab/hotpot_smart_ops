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
├── hotpot_platform/          # 云平台（Hub + Dashboard + 集成）
│   ├── cloud/         #  event_hub, llm_report, vlm_review, integrations
│   └── dashboard/     #  HTML 前端面板
├── edge/              # 边缘端
│   ├── agent/         #  Edge Agent 服务器（FastAPI :9100）
│   ├── front-hall/    #  前厅推理（YOLO + CLIP 场景分析）
│   │   └── stream/    #    scene_analyzer.py, clip_server.py
│   ├── kitchen/       #  后厨推理（VLM 废料识别）
│   └── shared/        #  共用 detector, models, scripts
├── docs/              # 方案文档与 ADR
│   ├── kitchen_loss_real_device_solution.md  # SSOT
│   └── kitchen_loss_budget_solution.md       # 执行附录
└── tests/             # 自动化验收测试
```

## 前厅场景分析

**文件**: `edge/front-hall/stream/scene_analyzer.py` + `clip_server.py`
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