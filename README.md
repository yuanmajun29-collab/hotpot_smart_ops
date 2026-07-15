# hotpot_smart_ops · 火瞳 — 项目总览

> 品牌: **火瞳** 🔥👁️ · 火锅后厨AI智能运营系统
> 产品: B2B SaaS · 边缘AI + 视觉检测 + 数据看板
> 状态: MVP已就绪 · 冯校长店验证中
> 最后整理: 2026-07-15 · 小馬V20260715233331

---

## 一句话

「火锅店老板的手机后厨——不在店里，也知道每盘菜去了哪」

---

## 项目全貌

```
hotpot_smart_ops/           (~536 文件 · 13 目录)
│
├── 📋 入口
│   ├── README.md           ← 你在这里
│   ├── CLAUDE.md           ← Claude Code 项目指引
│   ├── requirements.txt    ← Python 依赖
│   └── yolov8n.pt          ← YOLO 权重 (6.2MB)
│
├── 🧠 推理层
│   ├── edge/               (78文件 · 17MB)
│   │   ├── agent/          ← 统一 Edge Agent :9100
│   │   ├── kitchen/        ← 后厨推理（YOLO→CLIP→VLM 可插拔管线）
│   │   ├── front_hall/     ← 前厅推理（plan_b 40ms / plan_a 190ms 双模式）
│   │   └── common/         ← 共用模块
│   │
│   └── common/             (5文件 · 32KB)  ← 边缘端 + 平台端共用
│
├── ☁️ 平台层
│   ├── hotpot_platform/    (217文件 · 93MB)  ← Hub :8098 + Dashboard
│   └── dashboard/          (42文件 · 28MB)   ← 前端 Dashboard :9120
│
├── 🚀 部署层
│   ├── deploy/             (20文件 · 96KB)   ← Jetson/云端部署脚本
│   ├── cloud/              (1文件 · 4KB)     ← 云端配置
│   └── scripts/            (28文件 · 172KB)  ← 运维/工具脚本
│
├── 🧪 测试 & 演示
│   ├── tests/              (40文件 · 212KB)  ← 176测试 · ~85%覆盖
│   ├── demo/               (83文件 · 9.6MB)  ← 演示素材
│   └── test_images/        (6文件 · 1.3MB)   ← 测试图片
│
├── 📚 文档中心
│   └── docs/               (19文件 · 308KB)
│       ├── 📋 PRD
│       │   ├── PRD-技术架构-v3.10.md            ← 小抠出品 · 768行/38KB
│       │   └── PRD-火瞳-火锅后厨AI智能运营系统-v1.0.md ← 小居出品 · 545行/29KB
│       │
│       ├── 🍲 全链路调研
│       │   ├── 火锅AI-市场调研.md               ← 市场规模/竞品空白
│       │   ├── 火锅AI-可行性分析.md             ← 技术/商业四维验证
│       │   ├── 火锅AI-产品定位.md               ← 差异化定位 + 定价
│       │   ├── 火锅AI-产品定位-竞品差异化分析.md ← 8款SaaS全扫描
│       │   ├── 火锅AI-开发方案.md               ← 架构/路线图/部署
│       │   ├── 火锅AI-推广策略.md               ← 漏斗/社群/90天
│       │   └── 火锅AI-GitHub精华吸收.md         ← 5高星项目借鉴
│       │
│       └── 📐 架构 & 产品设计
│           ├── PROJECT_OVERVIEW.md
│           ├── product_design.md
│           ├── product_overview.md
│           ├── product_goal_card.md
│           ├── solution.md
│           ├── architecture_api_spec.md
│           ├── architecture_decisions.md
│           └── autonomous_dev_roadmap.md
│
└── ✋ 工作交接
    └── handoff/            (3文件 · 12KB)   ← AI工具间交接文件
```

---

## 核心模块

| 模块 | 路径 | 行/文件 | 成熟度 | 说明 |
|------|------|---------|--------|------|
| Edge Agent | `edge/agent/` | ~500行 | 🟢 生产 | 设备注册+心跳+配置热加载 |
| 后厨推理 | `edge/kitchen/` | ~3000行 | 🟡 测试 | YOLO→CLIP→VLM可插拔 |
| 前厅推理 | `edge/front_hall/` | ~2000行 | 🟡 测试 | plan_a/plan_b双模式 |
| Hub | `hotpot_platform/` | ~15000行 | 🟢 生产 | :8098, 18路由域 |
| Dashboard | `dashboard/` | ~8000行 | 🟢 生产 | :9120, 15+页面 |
| 部署脚本 | `deploy/` | ~1500行 | 🟡 测试 | 10 Phase Jetson部署 |
| 自动化测试 | `tests/` | ~4000行 | 🟢 生产 | 176测试, ~85%覆盖 |

---

## 产品状态

| 阶段 | 状态 | 产出 |
|------|:--:|------|
| 🔍 市场调研 | ✅ | → `docs/火锅AI-市场调研.md` |
| 🎯 可行性分析 | ✅ | → `docs/火锅AI-可行性分析.md` |
| 📌 产品定位 | ✅ | → `docs/火锅AI-产品定位.md` |
| 🛠️ 开发方案 | ✅ | → `docs/火锅AI-开发方案.md` |
| 📣 推广策略 | ✅ | → `docs/火锅AI-推广策略.md` |
| 📋 PRD | ✅ | → `docs/PRD-*.md` (2份) |
| 🔍 GitHub借鉴 | ✅ | → `docs/火锅AI-GitHub精华吸收.md` |

---

## 定价

| 档位 | 硬件 | 年费 | 目标 |
|------|------|------|------|
| 基础 | ¥18,800 | ¥7,800 | 3-10店 |
| 专业 | ¥25,800 | ¥15,800 | 10-30店 |
| 企业 | ¥45,000+ | ¥28,800 | 30+连锁 |

---

## 下一步

- [ ] Count Anything 模型部署到 Jetson
- [ ] 冯校长店完整功能上线
- [ ] 第2-3家试用客户签约
- [ ] Supervision 集成（可视化+追踪）
- [ ] YOLO TensorRT 导出加速

---

*关联知识库: `Obsidian/study/books/AI超级个体/` · `Obsidian/study/market/`*
