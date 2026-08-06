## Agent NL MVP — 最小规则原型

> 🟡 **dev/demo 规则原型 · 禁止用于生产决策**
> MVP阶段使用模拟数据。展前仅验证"微信→规则→推送"闭环，展后接入真实DB和LLM。
> 所有数据均为展示用示例，不反映真实门店经营数据。

---

## 一、设计目标

展前不求完整 NL，只打通"微信→推送"闭环。展会后接 LLM 升级为完整 Agent。

| 阶段 | 能力 | 技术 |
|------|------|------|
| **MVP（展前）** | 关键词规则匹配 → 数据查询 → 微信推送 | 规则引擎 + Webhook |
| **V2（展后）** | 自然语言理解 → 意图识别 → 多轮对话 | LLM + RAG |

---

## 二、MVP 功能范围

### 2.1 支持的关键词组

| 关键词 | 意图 | 数据源 | 推送目标 |
|--------|------|--------|---------|
| `损耗` `废料` `浪费` | 查询今日损耗 | `daily_waste` 表 | A02 后厨助理 |
| `翻台` `桌态` `上座` | 查询翻台率 | `turnover` 统计 | A01 店长助理 |
| `温度` `冷柜` `报警` | IoT 告警状态 | `iot_alerts` 表 | A02 后厨助理 |
| `日报` `报告` | 今日运营日报 | 聚合多表 | A01 店长助理 |
| `库存` `备货` | 库存快照 | `inventory_snapshot` | A02 后厨助理 |
| `SOP` `合规` `违规` | SOP 评分 | `sop_scores` 表 | A02 后厨助理 |

### 2.2 不做的

- ❌ 多轮对话
- ❌ 模糊意图消歧
- ❌ 自然语言生成（固定模板回复）
- ❌ 语音输入

---

## 三、架构

```
微信消息（文本）
    │
    ▼
OpenClaw Gateway (:18789)
    │
    ▼
Webhook → Hub (:8098)
    │
    ▼
NL Rule Engine (nl_router.py)
    │ keyword match ──→ intent ──→ data query ──→ template render
    ▼
WeChat API → 微信推送
```

### 新增文件

| 文件 | 作用 |
|------|------|
| `hotpot_platform/cloud/event_hub/nl_router.py` | 规则引擎：关键词→意图→查询→模板 |
| `hotpot_platform/cloud/event_hub/routers/nl_webhook.py` | Webhook 入口：接收微信消息 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `hotpot_platform/cloud/event_hub/server.py` | 注册 `/webhook/nl` 路由 |
| `deploy/.env.example` | 新增 `WECHAT_CALLBACK_TOKEN` |

---

## 四、API 设计

### 4.1 Webhook 接入

```
POST /webhook/nl
Content-Type: application/json

{
  "from_user": "o9cq80xc2kaa6kHj6KqmS9SRV24s",
  "text": "今天损耗多少",
  "timestamp": 1786000000
}
```

### 4.2 响应

```json
{
  "intent": "query_waste",
  "matched_keyword": "损耗",
  "reply": "📊 今日损耗报告\n废料: 3盘\n金额: ¥156\n趋势: ↓12% vs 昨日",
  "push_target": "A02",
  "data": { ... }
}
```

---

## 五、数据模板

### 损耗查询模板

```
📊 {store_name} 今日损耗
废料检测: {waste_count} 盘
预估金额: ¥{waste_amount}
趋势: {trend_icon} {trend_pct}% vs 昨日
📍 {timestamp}
```

### 日报模板

```
📋 {store_name} 运营日报 [{date}]
翻台率: {turnover_rate}
损耗: ¥{waste_amount}
IoT告警: {alert_count}条
SOP评分: {sop_score}分
📍 {timestamp}
```

---

## 六、落地计划

| 步骤 | 内容 | 估时 |
|:--:|------|:--:|
| 1 | 创建 `nl_router.py` — 关键词规则引擎 | 0.5h |
| 2 | 创建 `nl_webhook.py` — Webhook 路由 | 0.5h |
| 3 | 注册路由到 `server.py` | 0.2h |
| 4 | 配置微信回调 token | 0.2h |
| 5 | 端到端测试：微信发消息→收推送 | 0.5h |
| | **合计** | **~2h** |
