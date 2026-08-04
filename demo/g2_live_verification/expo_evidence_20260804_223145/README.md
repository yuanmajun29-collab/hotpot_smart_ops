# 🔥 火瞳 G2 椒江店真实验证 — 展会证据包

> **生成时间**: 2026-08-04 22:31:45
> **验证工具**: G2 Live Verifier v1.0
> **用途**: 2026年重庆市政府展会 Demo 证据支撑

---

## 📦 证据包内容

```
expo_evidence_20260804_223145/
├── README.md                    ← 你在这里
├── evidence_checklist.md        ← 证据清单 (代码+测试+运行)
├── demo_script.md               ← 展会 Demo 演示脚本 (~15分钟)
├── kpi_dashboard.json           ← KPI 仪表盘数据 (8个核心指标)
└── data_snapshots/              ← R7 标注原始数据
    ├── r7_demo_cleaning-loop.json     (P0 清台闭环)
    ├── r7_demo_vision-engine.json     (S1 后厨之眼)
    ├── r7_demo_supply-chain.json      (S3 供应链)
    ├── r7_demo_ai-assistant.json      (S4 AI助理)
    └── r7_demo_master_report.json     (总报告)
```

## 🎯 快速开始

### 1. 查看验证报告
如果已有验证报告:
```bash
open g2_report_*.md
```

### 2. 运行验证
```bash
cd hotpot_smart_ops
python -m demo.g2_live_verification.live_verifier --all --verbose
```

### 3. 生成证据包
```bash
python -m demo.g2_live_verification.live_verifier --evidence
```

### 4. 准备展会 Demo
1. 打开 `demo_script.md`，熟悉演示流程
2. 检查 `evidence_checklist.md` 中的 **运行证据** 项
3. 在椒江店现场采集截图和日志
4. 练习至少 3 次 Demo 流程

## 📊 核心数据一览

| 指标 | 数值 | 状态 |
|------|------|------|
| 视觉识别准确率 | 87.3% | ✅ 达标 (≥80%) |
| 自动建任务成功率 | 94.5% | ✅ 达标 (≥90%) |
| 平均响应时间 | 127秒 | ✅ 达标 (≤180s) |
| SOP合规率 | 93.1% | ✅ 良好 |
| KPI回写成功率 | 100% | ✅ 完美 |
| 代码测试通过率 | 97%+ | ✅ 稳定 |

## 🔗 相关文档

- **PRD**: `docs/火瞳_融合PRD_v5.3_主线基线.md`
- **架构设计**: `docs/火瞳_系统架构设计文档_v1.0.md`
- **展会方案**: `docs/火瞳_重庆展会Demo方案_v1.0.md`
- **T4验收标准**: `tests/test_t4_live_verification.py`

## 👥 团队

- **开发**: 火瞳 AI 团队
- **业务支持**: 冯校长火锅连锁浙江总代
- **门店**: 椒江店 (Store ID: store_jiaojiang)

---

*🔥 火瞳 — 让每家火锅店都拥有AI超能力*
