# Figma 组件清单与设计规格

**冯校长火锅 · 智能运营 · Phase 1 MVP · V1.0**

| 项目 | 内容 |
|------|------|
| 关联 PRD | [product_design.md](product_design.md) |
| PoC 参考 | `dashboard/index.html` |
| 目标交付 | Sprint 4（DEV-401/402/403）高保真 + Dev Mode 标注 |
| Figma 文件建议命名 | `Hotpot-SmartOps-Phase1` |

---

## 1. Figma 文件结构

```
Hotpot-SmartOps-Phase1
├── 📁 Cover & Docs
│   ├── Cover（封面）
│   ├── Changelog
│   └── 本规格链接
├── 📁 Foundations（设计基础）
│   ├── Colors
│   ├── Typography
│   ├── Spacing & Grid
│   ├── Icons
│   └── Elevation
├── 📁 Components（组件库）
│   ├── Atoms
│   ├── Molecules
│   ├── Organisms
│   └── Templates
├── 📁 Patterns（交互模式）
│   ├── 告警 / 空态 / 加载 / 错误
│   └── PDA 向导步骤条
├── 📁 Web · 门店看板（1440）
│   ├── Login
│   ├── Home
│   ├── Tables
│   ├── Kitchen
│   ├── SOP
│   ├── Cost
│   ├── Alerts
│   └── Report
├── 📁 Mobile · 店长 H5（390）
│   ├── Tab-Home
│   ├── Tab-Tables
│   ├── Tab-Alerts
│   └── Tab-Profile
├── 📁 PDA · 收货（480×800 竖屏）
│   └── Receiving Flow 1~5
└── 📁 Push · 企微卡片（参考）
    └── Alert Card Templates
```

---

## 2. Design Tokens

### 2.1 色彩（与 PoC 对齐，Figma Variables）

| Token | 值 | 用途 |
|-------|-----|------|
| `color/bg/primary` | `#0F1419` | 页面背景 |
| `color/bg/card` | `#1A2332` | 卡片背景 |
| `color/border/default` | `#2A3544` | 边框 |
| `color/text/primary` | `#E6EDF3` | 主文字 |
| `color/text/muted` | `#8B949E` | 次要文字 |
| `color/status/ok` | `#3FB950` | 空桌 / 通过 |
| `color/status/info` | `#58A6FF` | 用餐中 / 链接 |
| `color/status/warn` | `#D29922` | 待清台 / 警告 |
| `color/status/critical` | `#F85149` | 待结账 / 严重 |
| `color/accent/primary` | `#58A6FF` | 主按钮 |

**桌态四态（Table State）** — 组件 Variant 属性 `state`:

| state | 背景（15% 透明度） | 边框 |
|-------|-------------------|------|
| empty | ok | ok |
| dining | info | info |
| need_clean | warn | warn |
| checkout | critical | critical |

### 2.2 字体

| Token | 字体 | 字号 | 行高 | 用途 |
|-------|------|------|------|------|
| `text/h1` | Segoe UI / PingFang SC | 24px | 32px | 页面标题 |
| `text/h2` | Segoe UI / PingFang SC | 14px | 20px | 卡片标题（大写 tracking） |
| `text/body` | Segoe UI / PingFang SC | 14px | 22px | 正文 |
| `text/caption` | Segoe UI / PingFang SC | 12px | 18px | 元信息 |
| `text/stat` | Segoe UI / PingFang SC | 32px | 40px | KPI 数字 |
| `text/mono` | ui-monospace | 13px | 20px | 日报 Markdown |

### 2.3 间距与圆角

| Token | 值 |
|-------|-----|
| `space/xs` ~ `space/xl` | 4 / 8 / 12 / 16 / 24 / 32 px |
| `radius/sm` | 6px（单元格、输入框） |
| `radius/md` | 10px（卡片） |
| `radius/lg` | 16px（抽屉、Modal） |

### 2.4 栅格

| 端 | 画布宽 | 栅格 | 边距 |
|----|--------|------|------|
| Web 看板 | 1440px | 12 列 · 16px gutter | 24px |
| 手机 H5 | 390px | 4 列 · 12px gutter | 16px |
| PDA | 480px | 4 列 · 12px gutter | 16px |

---

## 3. 组件库清单

图例：🔴 P0 必做 · 🟡 P1 · ⚪ P2

### 3.1 Atoms（原子）

| 组件名 | Figma 路径 | Variant 属性 | 关联 PRD | 优先级 |
|--------|------------|--------------|----------|--------|
| `Button/Primary` | Atoms/Button | size: sm/md/lg · state: default/hover/disabled/loading | — | 🔴 |
| `Button/Secondary` | Atoms/Button | 同上 | — | 🔴 |
| `Button/Ghost` | Atoms/Button | 同上 | F-A03 ack | 🔴 |
| `Input/Text` | Atoms/Input | state: default/focus/error/disabled | — | 🔴 |
| `Input/Search` | Atoms/Input | — | F-A02 | 🟡 |
| `Badge/Level` | Atoms/Badge | level: info/warn/critical | F-A01 | 🔴 |
| `Badge/Count` | Atoms/Badge | — | 顶栏告警角标 | 🔴 |
| `StatusDot` | Atoms/StatusDot | online/offline | F-H01 | 🔴 |
| `Icon/*` | Atoms/Icons | 24px 线型：bell/table/thermo/scale/doc/alert/settings | — | 🔴 |
| `Avatar/User` | Atoms/Avatar | size: sm/md | 顶栏用户 | 🔴 |
| `Tag/TableState` | Atoms/Tag | empty/dining/need_clean/checkout | F-T01 | 🔴 |
| `Tag/SOPStatus` | Atoms/Tag | pass/fail/pending | F-S02 | 🔴 |
| `Tag/QualityGrade` | Atoms/Tag | A/B/C/D | F-C03 | 🔴 |
| `Divider` | Atoms/Divider | horizontal/vertical | — | 🔴 |
| `Skeleton/Block` | Atoms/Skeleton | — | 加载态 | 🟡 |

### 3.2 Molecules（分子）

| 组件名 | 组成 | Variant | 关联 PRD | 优先级 |
|--------|------|---------|----------|--------|
| `KPI/StatCard` | 标题 + Stat 数字 + 可选 trend | tone: ok/warn/critical/neutral | F-H02 | 🔴 |
| `Table/Cell` | 桌号 + 状态 Tag | state 四态 | F-T01 | 🔴 |
| `List/EventItem` | 左边框色条 + 消息 + 时间 | level: info/warn/critical | F-A01 | 🔴 |
| `List/SuggestionItem` | 序号 + 桌号 + 理由 + CTA | — | F-T03 | 🔴 |
| `List/SOPItem` | SOP 名 + 合规率 + 展开箭头 | expanded: true/false | F-S01 | 🔴 |
| `List/CostBatchItem` | SKU + 偏差 + 等级 Tag | variance: normal/warn | F-C01 | 🔴 |
| `List/IoTStageCard` | 来料/保存/加工 + 状态点 | stage + alert | F-K03 | 🔴 |
| `Nav/SidebarItem` | Icon + 文案 + active 态 | active, badge | §6 IA | 🔴 |
| `Nav/TabBarItem` | Icon + 文案 | mobile 4-tab | 手机 H5 | 🟡 |
| `Form/LoginField` | Label + Input + error | — | DEV-401 | 🔴 |
| `Chart/Sparkline` | 迷你温湿度曲线 | — | F-K01 | 🟡 |
| `Alert/InlineBanner` | 图标 + 文案 + 操作 | type | 页内提示 | 🟡 |
| `Empty/State` | 插画 + 文案 + 按钮 | module | 各列表空态 | 🟡 |
| `Stepper/PDA` | 1~5 步进度 | current step | F-P01~P07 | 🔴 |
| `Signature/Pad` | 签字区 + 清除 + 确认 | — | F-P06, F-S05 | 🔴 |

### 3.3 Organisms（组织）

| 组件名 | 说明 | 关联 PRD | 优先级 |
|--------|------|----------|--------|
| `Shell/AppHeader` | Logo + 门店名 + 班次 + 告警角标 + 连接态 + 用户 | F-H01, F-H04 | 🔴 |
| `Shell/Sidebar` | 7 项导航 + collapse | §6 IA | 🔴 |
| `Shell/MobileHeader` | 简化顶栏 | H5 | 🟡 |
| `Grid/TableFloor` | 桌位网格 · 可配置行列 | F-T01 | 🔴 |
| `Panel/TurnoverSuggestions` | Top5 翻台建议 | F-T03 | 🔴 |
| `Drawer/TableDetail` | 单桌时间线 + 纠正按钮 | F-T04, F-T06 | 🟡 |
| `Panel/EventStream` | 可滚动事件流 + 过滤器 | F-A01, F-A02 | 🔴 |
| `Panel/ReportViewer` | Markdown 渲染区 | F-R01, F-R02 | 🔴 |
| `Panel/SOPChecklist` | 检查点表格 | F-S02 | 🔴 |
| `Panel/CostSummary` | 汇总 + 批次列表 | F-C01~C04 | 🔴 |
| `Panel/IoTDashboard` | 温湿度 + 门磁 + 三阶段 | F-K01~K04 | 🔴 |
| `Modal/AlertAck` | 确认处理 + 备注 | F-A03 | 🔴 |
| `Modal/AssignFix` | 指派整改 | F-S04 | 🟡 |
| `Wizard/ReceivingPDA` | 5 步收货全流程 | F-P01~P07 | 🔴 |

### 3.4 Templates（页面模板）

| 模板 | Frame 尺寸 | 页面 |
|------|------------|------|
| `Template/Web-Authenticated` | 1440×900 | 除 Login 外所有 Web 页 |
| `Template/Web-Login` | 1440×900 | 登录 |
| `Template/Mobile-Tab` | 390×844 | H5 四 Tab |
| `Template/PDA-Full` | 480×800 | 收货向导 |

---

## 4. 页面 Frame 清单（高保真）

| Frame 名 | 路由 | PRD 功能 | Dev 任务 | 状态 |
|----------|------|----------|----------|------|
| `Web/Login` | `/login` | DEV-401 | DEV-401 | 待设计 |
| `Web/Home` | `/` | F-H01~H03 | DEV-402 | PoC 可参照 |
| `Web/Tables` | `/tables` | F-T01~T03 | DEV-402 | PoC 可参照 |
| `Web/Tables/Drawer` | overlay | F-T04~T06 | DEV-402 | 待设计 |
| `Web/Kitchen` | `/kitchen` | F-K01~K07 | DEV-402 | PoC 部分 |
| `Web/SOP` | `/sop` | F-S01~S05 | DEV-402 | PoC 部分 |
| `Web/SOP/Detail` | `/sop/:id` | F-S02 | DEV-402 | 待设计 |
| `Web/Cost` | `/cost` | F-C01~C05 | DEV-402 | PoC 部分 |
| `Web/Alerts` | `/alerts` | F-A01~A03 | DEV-402 | PoC 部分 |
| `Web/Report` | `/report` | F-R01~R04 | DEV-402 | PoC 可参照 |
| `Web/Report/History` | `/report/history` | F-R04 | DEV-402 | 待设计 |
| `Mobile/Home` | H5 Tab-Home | F-H02 | DEV-402 | ✅ HTML 原型 |
| `Mobile/Tables` | H5 Tab-Tables | F-T01~T03 | DEV-402 | ✅ HTML 原型 |
| `Mobile/Alerts` | H5 Tab-Alerts | F-A01~A03 | DEV-402 | ✅ HTML 原型 |
| `Mobile/Profile` | H5 Tab-Profile | — | DEV-402 | ✅ HTML 原型 |
| `PDA/Recv-Step1` | PO 选择 | F-P01 | DEV-403 | 待设计 |
| `PDA/Recv-Step2` | 称重 | F-P02 | DEV-403 | 待设计 |
| `PDA/Recv-Step3` | 测温 | F-P03 | DEV-403 | 待设计 |
| `PDA/Recv-Step4` | VLM 拍照 | F-P05 | DEV-403 | 待设计 |
| `PDA/Recv-Step5` | 签字提交 | F-P06 | DEV-403 | 待设计 |
| `Push/Alert-Critical` | 企微 | F-A04 | DEV-306 | 待设计 |
| `Push/Alert-Warn` | 企微 | F-A04 | DEV-306 | 待设计 |
| `Push/DailyReport` | 企微 | F-R01 | DEV-302 | 待设计 |

**Phase 1 最低交付 Frame 数**：18 个（Web 10 + PDA 5 + Push 3）

---

## 5. 组件 Variant 规格示例

### 5.1 `Table/Cell`

```
Properties:
  state: empty | dining | need_clean | checkout
  size: sm | md
  selected: true | false

Layout (md):
  Auto layout vertical, center
  Padding: 10px
  Min width: 72px
  Border: 1px solid [state border color]
  Fill: [state bg 15%]

Content:
  Line1: table_id (caption muted)
  Line2: state label (Tag/TableState)
```

### 5.2 `KPI/StatCard`

```
Properties:
  tone: neutral | ok | warn | critical
  hasTrend: true | false

Layout:
  Card padding 16px, radius md
  Title: text/h2 uppercase muted
  Value: text/stat [tone color]
  Optional: trend arrow + %
```

### 5.3 `List/EventItem`

```
Properties:
  level: info | warn | critical
  acked: true | false

Layout:
  Border-left 3px [level color]
  Padding 10px
  Opacity 0.6 if acked

Content:
  message (body)
  meta: time + source (caption)
  Action: [确认] if !acked && level != info
```

---

## 6. 交互与原型链接

| 流程 | 起始 Frame | 交互 | 原型必连 |
|------|------------|------|----------|
| 登录 | Web/Login | Submit → Web/Home | 🔴 |
| 查看待清桌 | Web/Home | 点击待办 → Web/Tables | 🔴 |
| 确认告警 | Web/Alerts | 点击 ack → Modal → 状态更新 | 🔴 |
| 收货全流程 | PDA/Recv-Step1 | Next×5 → 成功页 | 🔴 |
| 生成日报 | Web/Report | 按钮 → 加载 → 渲染 | 🔴 |
| 单桌纠正 | Web/Tables | Cell → Drawer → 改状态 | 🟡 |

**Figma Prototype 设置**：Instant · Dissolve 200ms · 保留滚动位置

---

## 7. Dev Mode 交付规范

| 项 | 要求 |
|----|------|
| 组件命名 | `Category/Name/Variant` 与上表一致 |
| 间距 | 全部 Auto Layout，禁绝对定位堆叠（图标除外） |
| 颜色 | 全部绑 Variables，禁硬编码 hex |
| 图标 | SVG export 24×24，统一 stroke 1.5 |
| 标注 | 每 Frame 附「PRD ID + API」注释层 |
| 切图 | 仅 Logo、空态插画；其余 CSS 实现 |
| 响应式 | Web 1440 为主；1280 测 Sidebar collapse |

### API 注释示例（贴在 Frame 右上角）

```
API: GET /v1/stores/{id}/summary
Refresh: 5s
PRD: F-H02, F-T01
```

---

## 8. 设计 QA Checklist（交付前）

- [ ] 所有颜色使用 Variables
- [ ] 桌态四态与 PoC 色值一致
- [ ] P0 组件全部入库 Components，非 Detached
- [ ] Web 7 页 + PDA 5 步 + Login 齐全
- [ ] critical/warn/info 三级告警视觉可区分
- [ ] 空态/加载态/错误态至少各 1 个 Pattern
- [ ] 每个 Frame 标注 PRD ID
- [ ] Prototype 4 条主流程可点击走通
- [ ] 与设计评审记录存档

---

## 9. 版本记录

| 版本 | 日期 | 说明 |
|------|------|------|
| V1.0 | 2026-06-12 | Phase 1 MVP 组件清单 |

**下一步**：设计师按 §4 Frame 清单建稿 → 与店长做概念测试 → Dev Mode 交付前端（DEV-402/403）
