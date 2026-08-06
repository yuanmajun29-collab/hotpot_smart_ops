# hotpot_smart_ops · 火瞳 — 项目总览

> 品牌: **火瞳** 🔥👁️ · 冯校长火锅连锁AI运营中台
> 产品: 视觉+数据双引擎 · 边缘AI + 视觉检测 + 数据引擎 + 运营看板
> 定位: 自有连锁内部运营系统（先服务自己，再对外输出）
> 状态: **🔧 D1 展会冲刺** (基于 `feature/d1-expo-sprint`) · 见下方「成熟度」
> 分支: `feature/d1-expo-sprint` (已融合 arch-design 架构整改)
> 最后整理: 2026-08-06

---

## 成熟度体系

本文档采用**四级成熟度**标注每项能力的真实状态：

| 等级 | 标识 | 含义 | 证据要求 |
|------|:----:|------|----------|
| L1 需求已定义 | 📋 | PRD/设计文档已完成 | 文档评审通过 |
| L2 代码原型 | 🔧 | 有可运行的代码/Demo | 单元测试通过 |
| L3 真实门店验证 | ✅ | 在椒江/玉环店真实运行 | 7天连续数据 + KPI回写 |
| L4 生产可用 | ⭐ | 可稳定支撑日常运营 | 多店复用 + ROI验证 |

> **重要**: 以下所有状态均基于真实证据。不存在"95% READY""两店已完成"等无法由证据支持的表述。

---

## 一句话

「摄像头替你看后厨，AI 替你算订货，手机上管所有店。」

---

## 文档中心

```
docs/
├── 01-核心权威/          # 权威文档（5份）★最新
│   ├── 火瞳_融合PRD_v5.3_主线基线.md           ← **v5.3o**, 129项功能, **~3500行** ★唯一权威（含通用化改造基线§1.11）
│   ├── 火瞳_系统架构总体设计_v2.0.md           ← **v2.1**, 4+1视图方法论, ~1478行 ★架构权威
│   ├── 火瞳_详细架构设计_v1.0.md              ← **v1.5**, 接口+数据模型+API+协议+部署, ~3470行 ★可执行级
│   ├── 火瞳_解决方案架构设计_v1.0.md           ← 四层技术架构(基础文档), 716行
│   └── 火瞳_解决方案架构可行性分析_20260729.md  ← 6维度, 71分B+, GO
│
├── 02-市场调研/          # 市场分析（2份）
│   ├── 火瞳_全网市场调研与可行性评估报告_v2.0_20260728.md  ← 7+10家竞品, 86分A-
│   └── 火瞳_PRD_v5.3c_市场调研与竞品评估报告_20260728.md   ← 10家竞品+行业趋势
│
├── 03-产品设计/          # 产品分析（5份）
│   ├── 产品设计-全面分析.md                     ← 8维分析
│   ├── 项目全貌-深度理解.md                     ← 9维整合(含代码实况)
│   ├── 火锅AI-经营哲学.md                       ← "拿得少，走得远"
│   ├── 火锅AI-思想源-梁文锋DeepSeek演讲.md      ← 思想源
│   └── 火锅AI-思想源-Harness-Engineering-UI设计规范.md
│
├── 04-技术设计/          # 技术文档（5份）
│   ├── 火锅AI-数据引擎技术设计-v1.0.md          ← N01-N06, 1431行
│   ├── PRD_V5_3i_CODE_ALIGNMENT.md              ← v5.3i基线版(★已升级至v5.3n，见01-核心权威/)
│   ├── PROJECT_BASELINE_V5_2.md                 ← 项目基线
│   ├── DATA_SOURCES.md                          ← 数据源定义
│   └── DATA_STANDARD.md                         ← 数据标准
│
├── 05-功能规格/          # Spec/测试/评审（10份）
│   ├── spec-K01-kitchen-waste-detection.md
│   ├── spec-K002-trend-alert.md
│   ├── spec-K003-daily-report.md
│   ├── spec-p0-api-buffer.md
│   ├── spec-phase2-receiving-sop-cockpit.md
│   ├── test_cases-K01-kitchen-waste-detection.md
│   ├── test_cases-K002-trend-alert.md
│   ├── test_cases-K003-daily-report.md
│   ├── review-K01-codex-20260716.md
│   └── review-K002-20260716.md
│
├── 06-调研照片/          # 实地照片（6区域35张）
│   ├── warehouse-survey/         ← 仓库区(3张)
│   ├── processing-survey/        ← 加工区(8张)
│   ├── hotprocessing-survey/     ← 热加工区(3张)
│   ├── dishwashing-survey/       ← 洗碗间(3张)
│   ├── fronthouse-survey/        ← 前厅(16张)
│   └── privateroom-survey/       ← 小包间(2张)
│
├── 07-业务参考/          # 业务数据（3份）
│   ├── 冯校长数据采集表.md
│   ├── 火瞳_重庆展会Demo方案_v1.0.md          ← 10月展会5场景+D1-D4冲刺
│   └── 火瞳_浙江总代门店标准与权益包_v1.0.md   ← 定价+权益
│
└── archive/              # 历史归档（15份，已扁平化）
    ├── PRD-技术架构-v3.10.md
    ├── PRD-火瞳-火锅后厨AI智能运营系统-v1.0.md
    ├── PRD评审-*.md (2份)
    ├── d1-expo-sprint-*.md (4份)
    ├── 火锅AI-*.md (4份)
    ├── architecture_decisions.md
    ├── jetson-vlm-bridge-v1.md                  ← 原在api-contracts/子目录(已扁平化)
    └── README.md
```

---

## 代码结构

```
hotpot_smart_ops/
├── edge/                  (94 py文件)  ← 边缘AI推理
│   ├── agent/             ← 统一Edge Agent :9100
│   ├── kitchen/           ← 后厨推理（YOLO→CLIP→VLM 7段管线）
│   ├── front_hall/        ← 前厅推理（plan_b 40ms / plan_a 190ms）
│   ├── iot_food_safety/   ← IoT传感（温度/湿度/RFID）
│   ├── receiving/         ← 收货验收
│   ├── staff_behavior/    ← 员工行为
│   └── common/            ← 共用模块
│
├── hotpot_platform/       (95文件)     ← 云端平台
│   ├── cloud/
│   │   ├── event_hub/     ← Hub API :8098（18路由域）
│   │   ├── data_engine/   ← 数据引擎（3566行，N01-N06）
│   │   ├── alert_gateway/ ← 告警网关
│   │   ├── sop/           ← SOP引擎
│   │   ├── llm_report/    ← LLM报告
│   │   ├── cost_control/  ← 成本管控
│   │   └── integrations/  ← 外部集成
│   ├── dashboard/         ← 前端看板（admin/mobile/pda）
│   └── deploy/            ← 部署配置
│
├── tests/                 (45文件)     ← 自动化测试（176测试，~85%覆盖）
├── scripts/               ← 运维脚本
├── deploy/                ← 部署脚本
├── demo/                  ← 演示素材
└── common/                ← 共用代码
```

---

## 核心指标

| 指标 | 目标 | 当前 | 成熟度 |
|------|------|:----:|:------:|
| 功能总数 | 129项(PRD **v5.3n**) | **71项有代码(55%)** | L2 代码原型 |
| 预测准确率(MAPE) | ≤15% | **10.6%** (椒江90天回测) | L2 代码原型 |
| 损耗闭环(玉环) | 7/7 Pass | **7/7** (14天模拟数据) | L2 代码原型 |
| 前厅推理延迟 | <50ms | **~40ms** (本地测试) | L2 代码原型 |
| 测试覆盖(单元) | ≥85% | **~85%** (176测试) | L2 代码原型 |
| Edge UI页面 | 17个HTML + 15API | ✅ 已实现 | L2 代码原型 |
| Agent Gateway | 22 ActionType + 审计 | ✅ 已部署Jetson | L2 代码原型 |
| 真实门店验证(椒江) | 7天连续运行 | ⚠️ Demo模式，非生产运行 | L1 需求已定义 |
| 单店年节省ROI | ≥¥15万 | 待真实门店验证 | L1 需求已定义 |

### 关键差距（整改方案 v1.0 已识别）

- 🔴 收货 VLM 仍为 Mock，未接入真实 Bridge
- 🔴 多摄像机配置已就绪但未完成 7 天真实验证
- 🔴 岗位 Agent 缺少统一自然语言入口 + 推送回执机制
- 🟡 销售增长/服务培训闭环尚未进入 PRD 正式业务域
- 🟡 "两店验证"仅完成回测+模拟，非真实生产环境连续运行

---

## 📋 开发完成状态（代码原型级别 L2）

> 以下为已完成的**代码/Demo交付物**，不等同于真实门店生产验证（L3/L4）。

```
🔧 Sprint 0        → 28项已有代码 (MAPE 10.6%, 损耗 7/7) [L2]
🔧 D1 冻品供应链   → S01-S04 全部完成 (货品/质检/采购/供应商) [L2]
🔧 D2 岗位AI助理   → A01-A05 全部完成 (4角色工作台+AI引擎) [L2]
🔧 D3 集成引擎     → IP-1~IP-5 全部通过 (EventBus跨模块集成) [L2]
🔧 D4 展会演示     → Demo + Web UI + 彩排物料 + 操作手册v2.0 [L2]
🔧 P0 修正         → IP-5合规 + Gateway中间件 (符合最终方案) [L2]
🔧 P1 增强         → 审计日志持久化 + Dashboard审批面板 [L2]
🔧 Jetson部署      → 边缘盒子稳定 (API<5ms, CPU 0.1%) [L2]
🎬 展会(10月重庆)  → 计划以 Demo 形式亮相，非生产级展示
```

---

## 三阶段路线

| 阶段 | 目标 | 门槛 | 当前状态 |
|------|------|------|:--------:|
| **两店验证** | 椒江、玉环真实数据和流程跑通 | 7天连续运行 + KPI回写 + ROI前后对照 | 📋 L1→L2 过渡中 |
| **区域标准化** | 形成浙江新店部署与运营标准 | 真实ROI数据 + 可复用部署包 | 📋 L1 需求已定义 |
| **对外输出** | 向体系内及外部连锁复制 | 稳定交付+合规定价+多店验证 | ⏳ L1 需求已定义 |

> **当前实际位置**: 处于「两店验证」阶段早期 — 有代码原型和 Demo，但尚未完成椒江店 7 天真实生产环境连续运行。展会（2026年10月重庆）将以 Demo 形式展示系统能力，不等同于生产级交付。

---

## 📦 展会交付物 (Demo 级别，非生产级)

> 以下为 2026年10月重庆展会准备的 **Demo 演示物料**，用于展示系统能力和设计意图。
> **不等同于**已完成真实门店生产验证（L3/L4）。

### 代码交付物 (L2 代码原型)
- ✅ Edge UI FastAPI (17页面 + 15API + JS模块)
- ✅ Agent Gateway (22 ActionType + 审计日志)
- ✅ D3集成引擎 (IP-1~IP-5 EventBus跨模块集成)
- ✅ Demo Runner (5场景彩排脚本 + IP-5双方案演示)
- ✅ 应急包 (3套数据集 + 一键启动脚本)

### 文档交付物
- ✅ PRD **v5.3n** 主线基线 (129项功能, ~3226行) — 📋 唯一权威（含红线+成熟度+样板店基线+Agent设计）
- ✅ 系统架构设计 **v2.1** (含Hub主写+Gateway) — 📋 架构权威
- ✅ 详细架构设计 **v1.5** (接口收敛+129项映射) — 📋 开发参考
- ✅ 整改方案 v1.0 (外部合规基准) — 📋 合规基准
- ✅ 展会现场操作手册 v2.0 (15分钟Demo脚本) — 🔧 Demo级
- ✅ Jetson稳定性测试报告 (A+ 98/100, 压测环境) — 🔧 Demo级

### Git版本信息
```
分支: feature/d1-expo-sprint (已融合 arch-design 架构整改)

关键Commit (D1-D4 冲刺期):
├─ 33fc620  P0-1 IP-5逻辑修正 (符合最终方案第六章)
├─ b34526b  P0-2 Agent Gateway中间件 (22 ActionType权限控制)
├─ 97bc0b0  P0-A/B/C/D 椒江样板店全链路融合改造
├─ 62f612e  P1 API路径统一+6大增强
├─ a3c3144  Expo视频生成器优化 (Jetson真实画面34.5MB)
└─ fdccc37  文档体系完善 (全链路追溯+元数据统一)
```

---

## 🚀 快速开始

### 本地开发
```bash
# 克隆仓库
git clone -b feature/d1-expo-spring https://github.com/yuanmajun29-collab/hotpot_smart_ops.git
cd hotpot_smart_ops

# 启动Edge UI (本地)
cd edge/edge-ui
python3 main.py
# 访问 http://localhost:9080
```

### Jetson边缘盒子部署
```bash
# SSH连接椒江店Jetson
ssh root@172.16.1.60

# 启动Edge UI
cd /opt/hotpot-smart-ops
bash start-edge-ui-fastapi.sh
# 访问 http://172.16.1.60:9080

# 启动Demo展示
bash demo/scripts/expo_demo_full.sh
```

### 云端平台
```bash
# 腾讯云 Dashboard
http://43.139.143.12:8098/login.html
# Demo账号: zhangdian/demo (店长) / admin/admin (PMO)
```

---

## 📞 联系方式

- **项目Owner**: 冯校长火锅连锁浙江总代
- **技术支持**: 火瞳开发团队
- **展会时间**: 2026年10月 · 重庆市政府展会（Demo展示）
- **当前分支**: `feature/d1-expo-sprint` (展会冲刺)
- **权威整改方案**: `docs/01-核心权威/火瞳_整改方案_v1.0_20260804.md`
- **文档版本**: v1.1-maturity-fix (2026-08-06) — 引入成熟度体系，统一口径
