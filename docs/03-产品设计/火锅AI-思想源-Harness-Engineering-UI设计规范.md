# Harness Engineering × UI设计规范 — 六层模型打通产品·设计·前端

> 来源: "AI工程化实战派"公众号 | 2026-07-24 吸收
> 核心思想: 用规范和验证层约束AI Agent产出可靠UI代码

---

## Harness Engineering 六层模型

```
规范层 ──→ 上下文层 ──→ 执行层 ──→ 验证层 ──→ 部署层 ──→ 审查层
Design    组件库+      Figma→Token  视觉回归+   Token版本化   反馈闭环
Tokens    .cursorrules  自动同步     UI Lint     组件库发布
```

| 层 | 产出物 | 作用 |
|----|--------|------|
| 1. 规范层 | Design Tokens JSON | color/spacing/radius/typography 的结构化定义，人和AI都能读 |
| 2. 上下文层 | 组件库文档 + `.cursorrules` UI章节 | AI知道项目有什么组件、怎么用、禁止什么 |
| 3. 执行层 | Figma→Token→代码自动同步管道 | 设计师改token → CI自动同步到代码仓 |
| 4. 验证层 | 视觉回归测试 + ESLint UI规则 | 禁止硬编码颜色/像素/内联样式 |
| 5. 部署层 | Token版本化 + 组件库独立发布 | Breaking Change流程·lock版本 |
| 6. 审查层 | 反馈闭环 | lint错误率统计→优化规则·设计反馈→补token |

---

## 与火瞳超体架构的映射

| Harness层 | 火瞳对标 | 现状 |
|----------|---------|:---:|
| **规范层** | ❌ 无 Design Tokens | 🔴 缺失 |
| **上下文层** | CLAUDE.md 架构描述 | 🟡 有架构·无UI规则 |
| **执行层** | 小卡(前端) + 小抠(后端) 协作 | 🟡 人工桥接 |
| **验证层** | 小居 Verifier + codejudge | 🟡 只验代码·不验UI |
| **部署层** | 小派 PilotDeck | 🟢 已有 |
| **审查层** | 双审查(小抠+小居) + 红军 | 🟢 已有 |

**最大缺口**: 1-3层完全没有 → AI生成前端代码没有UI约束 → 颜色/间距/组件每次都要人工调。

---

## 火瞳可直接落地的三步

### Step 1: 建立 Design Tokens (规范层)
创建 `hotpot_platform/tokens/design-tokens.json`:
- 黑色/白色/火锅红 为主色调
- 仪表盘卡片间距
- 告警状态颜色 (🟢🟡🔴)

### Step 2: 写进 CLAUDE.md (上下文层)
在 CLAUDE.md 新增 `## UI 规范` 章节:
- 所有卡片用 Card 组件
- 告警状态色从 token 取
- 禁止硬编码像素/颜色

### Step 3: 加 Lint 规则 (验证层)
增强 codejudge 或新增 `ui-lint` 检查:
- 扫描硬编码颜色值 (#xxx)
- 扫描内联样式
- 扫描裸 `<button>` (应使用 Button 组件)

---

## 一句话

> **AI生成UI的最大问题不是AI不行，是没有给它设计好约束环境。**
> 火瞳的L2闭环质量体已经覆盖了验证-部署-审查，缺的是规范-上下文-执行这三层。
