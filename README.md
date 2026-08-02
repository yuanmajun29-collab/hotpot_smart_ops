# hotpot_smart_ops · 火瞳 — 项目总览

> 品牌: **火瞳** 🔥👁️ · 冯校长火锅连锁AI运营中台
> 产品: 视觉+数据双引擎 · 边缘AI + 视觉检测 + 数据引擎 + 运营看板
> 定位: 自有连锁内部运营系统（先服务自己，再对外输出）
> 状态: **✅ 展会就绪 v0.4.0-expo-ready** (2026-10 重庆) · 椒江店回测Go(MAPE 10.6%) · 玉环店损耗闭环Pass(7/7)
> 分支: `feature/d1-expo-sprint` (基于 `main`)
> Tag: `v0.4.0-expo-ready`
> 最后整理: 2026-08-02

---

## 一句话

「摄像头替你看后厨，AI 替你算订货，手机上管所有店。」

---

## 文档中心

```
docs/
├── 01-核心权威/          # 权威文档（5份）★最新
│   ├── 火瞳_融合PRD_v5.3_主线基线.md           ← v5.3i, 129项功能, **2839行** ★唯一权威
│   ├── 火瞳_系统架构总体设计_v2.0.md           ← 4+1视图方法论, 10章节, 1478行 ★架构权威
│   ├── 火瞳_详细架构设计_v1.0.md              ← 接口+数据模型+API+协议+部署, 1996行 ★可执行级
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
│   ├── PRD_V5_3i_CODE_ALIGNMENT.md              ← v5.3i全量129项功能代码状态矩阵(25.6%覆盖率) ★最新
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

| 指标 | 目标 | 当前 |
|------|------|:----:|
| 功能总数 | 129项(PRD v5.3i) | **71项有代码(55%)** |
| 预测准确率 | MAPE ≤15% | 10.6% ✅ |
| 损耗闭环 | 7/7 Pass | ✅ |
| 前厅推理延迟 | <50ms | ~40ms ✅ |
| 测试覆盖 | ≥85% | ~85% ✅ |
| Edge UI页面 | 17个HTML + 14API | ✅ **完整** |
| Agent Gateway | 22 ActionType + 5 RiskLevel | ✅ **已部署** |
| 审计日志持久化 | JSONL双写+90天保留 | ✅ **已实现** |
| Jetson稳定性 | A+ (98/100) | ✅ **验证通过** |
| 单店年节省 | ≥¥15万(保守)/≥¥28万(估算) | 待展会验证 |
| 展会就绪度 | 2026年10月重庆 | **✅ 95%+ READY** |

---

## 🎯 展会冲刺完成状态

```
✅ Sprint 0        → 28项已有代码 (MAPE 10.6%, 损耗 7/7)
✅ D1 冻品供应链   → S01-S04 全部完成 (货品/质检/采购/供应商)
✅ D2 岗位AI助理   → A01-A05 全部完成 (4角色工作台+AI引擎)
✅ D3 集成引擎     → IP-1~IP-5 全部通过 (EventBus跨模块集成)
✅ D4 展会演示     → Demo + Web UI + 彩排物料 + 操作手册v2.0
✅ P0 修正         → IP-5合规 + Gateway中间件 (符合最终方案)
✅ P1 增强         → 审计日志持久化 + Dashboard审批面板
✅ Jetson部署      → 边缘盒子A+稳定 (API<5ms, CPU 0.1%)
🎬 展会(10月)      → 重庆市政府展会亮相 ★ 下一步
```

---

## 三阶段路线

| 阶段 | 目标 | 门槛 | 状态 |
|------|------|------|:----:|
| **两店验证** | 椒江、玉环真实数据和流程跑通 | MAPE 10.6% + 损耗 7/7 + D1-D4全通过 | ✅ **完成** |
| **区域标准化** | 形成浙江新店部署与运营标准 | 展会亮相+真实ROI数据 | 🎯 **进行中(展会)** |
| **对外输出** | 向体系内及外部连锁复制 | 真实ROI+稳定交付+合规定价 | ⏳ 2027Q1 |

---

## 📦 展会交付物 (v0.4.0-expo-ready)

### 代码交付物
- ✅ Edge UI FastAPI (17页面 + 14API + 10JS模块)
- ✅ Agent Gateway (22 ActionType + 5 RiskLevel + 审计日志)
- ✅ D3集成引擎 (IP-1~IP-5 EventBus跨模块集成)
- ✅ Demo Runner (5场景彩排脚本 + IP-5双方案演示)
- ✅ 应急包 (3套数据集 + 一键启动脚本)

### 文档交付物
- ✅ PRD v5.3i 主线基线 (129项功能, 2839行)
- ✅ 系统架构设计 v1.0 (含Gateway章节)
- ✅ 最终方案合规基准 (P0修正+ADR记录)
- ✅ 展会现场操作手册 v2.0 (15分钟Demo脚本)
- ✅ 展会最终彩排验证报告 (5/5全通过 A+ 98分)
- ✅ Jetson稳定性测试报告 (A+ 98/100)
- ✅ 展会交付物清单 (`docs/展会交付物清单_v0.4.0-expo-ready.md`)

### Git版本信息
```
Tag: v0.4.0-expo-ready
分支: feature/d1-expo-sprint (已推送远程)

关键Commit (本次冲刺):
├─ 33fc620  P0-1 IP-5逻辑修正 (符合最终方案第六章)
├─ b34526b  P0-2 Agent Gateway中间件 (22 ActionType权限控制)
├─ f00e7a3  Gateway Jetson部署修复 (5项导入错误修复)
├─ 0c71e94  展会物料 (操作手册v2.0 + 应急包 + 三套数据集)
├─ 20e7f1d  Jetson稳定性压测 (A+ 98/100)
├─ 389070b  D4最终彩排验证 (5大场景+IP-5全通过)
├─ 16f0d77  审计日志持久化 (JSONL双写+历史查询API)
└─ 037828e  Dashboard审批面板 (实时状态显示)
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
- **展会时间**: 2026年10月 · 重庆市政府展会
- **文档版本**: v0.4.0-expo-ready (2026-08-02)
