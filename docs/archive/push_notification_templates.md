# 企微 / 推送通知模板

**冯校长火锅 · 智能运营 · Phase 1**

| 项目 | 内容 |
|------|------|
| 版本 | V1.0 |
| 关联 PRD | [product_design.md §8](product_design.md#8-告警与通知设计) · §7.4 |
| 关联研发 | DEV-306 · DEV-414~415 · DEV-424 |
| 环境变量 | `HOTPOT_WECHAT_WEBHOOK` · `HOTPOT_PUSH_WARN=0`（首月默认） |

---

## 1. 推送规则速查

| 规则 | 说明 |
|------|------|
| N-01 | critical 30s 内必达 |
| N-02 | 同 `table_id` 待清 5min 内合并 1 条 |
| N-03 | 22:00~08:00 非 critical 不推手机（可配） |
| N-04 | ack 后不再推；30min 未 ack 升级督导 |
| N-05 | **首月试点 warn 默认仅看板** |

| 级别 | 推手机 | 看板 |
|------|:------:|:----:|
| critical | ✅ 店长 + 厨师长 | ✅ |
| warn | ⚠️ 可配（默认否） | ✅ |
| info | ❌ | ✅ |

---

## 2. 告警卡片 · critical

**场景**：燃气、烟雾、冷链断链、门磁超时升级

**标题**：`【严重】{store_name} · {alert_type}`

**正文模板**：

```text
{store_name} · {zone}
{type_label}：{summary}
时间：{time_hhmm}
桌位/设备：{target_id}

👉 打开看板处理
{dashboard_url}/alerts.html?store={store_id}

[确认已处理] → ack 深链（Phase 1 可选）
```

**示例**：

```text
【严重】冯校长火锅·玉环店 · 后厨烟雾
后厨档口：烟雾检测触发
时间：14:32
桌位/设备：kitchen_01

👉 打开看板处理
http://ops.example.com/alerts.html?store=store_yuhuan
```

**Markdown 变量**

| 变量 | 来源 |
|------|------|
| `store_name` | Hub store config |
| `alert_type` | event.type |
| `summary` | event.message |
| `target_id` | event.table_id / device_id |
| `dashboard_url` | 店级 `HOTPOT_DASHBOARD_URL` |

---

## 3. 告警卡片 · warn

**场景**：短重、SOP 违规、待清超时（首月默认**不推手机**，仅存档模板）

**标题**：`【提醒】{store_name} · {alert_type}`

**正文模板**：

```text
{store_name}
{type_label}：{summary}
建议：{action_hint}

👉 查看详情
{dashboard_url}/{module}.html?store={store_id}
```

**示例（待清超时）**：

```text
【提醒】冯校长火锅·椒江店 · 待清台
T05 待清台已 12 分钟
建议：优先安排保洁清台

👉 查看详情
http://ops.example.com/tables.html?store=store_jiaojiang
```

**示例（短重）**：

```text
【提醒】冯校长火锅·玉环店 · 来料短重
批次 RCV-003 毛肚 偏差 -4.2%
建议：查看拒收建议并厨师长确认

👉 查看详情
http://ops.example.com/cost.html?store=store_yuhuan
```

---

## 4. 翻台任务卡片（领班 / 保洁）

**场景**：领班点击「派保洁」或系统自动派单（Phase 1 可为 warn 级）

**标题**：`【清台】{store_name} · {table_id}`

```text
{table_id} 待清台 · 已 {minutes} 分钟
优先级：{rank}/5
理由：{reason}

👉 前往清台
{dashboard_url}/tables.html?table={table_id}
```

---

## 5. 运营日报卡片

**场景**：22:00 自动生成后推送店长（DEV-424）

**标题**：`【运营日报】{store_name} · {date}`

```text
{date} 运营摘要
· 翻台：待清 {need_clean} 桌 · 翻台率 {turnover_rate}
· SOP：合规 {sop_rate}%
· 来料：偏差 {cost_var}%
· 安全：严重告警 {critical} 条（已处理 {acked}）

👉 查看完整日报
{dashboard_url}/report.html?store={store_id}&date={date}
```

---

## 6. 告警升级卡片（督导）

**场景**：critical/warn 30min 未 ack（F-A05 · DEV escalations）

**标题**：`【升级】{store_name} · 未处理告警`

```text
{store_name} 有 {count} 条告警超过 {threshold} 分钟未确认
最高级别：{max_level}
最近一条：{latest_summary}

👉 督导查看
{dashboard_url}/alerts.html?store={store_id}&filter=critical
```

---

## 7. 看板角标与列表文案

| 位置 | 文案规范 |
|------|----------|
| 侧栏告警角标 | 仅 **未 ack 的 critical** 数量 |
| 事件流 critical | 左边框 `#F85149` + 「确认」按钮 |
| 事件流 warn | `#D29922` |
| 事件流 info | 灰色，无推送 |
| ack 后 | 行置灰 + 「已确认 · {ack_by} · {time}」 |

---

## 8. 企微机器人 JSON 参考（markdown 类型）

```json
{
  "msgtype": "markdown",
  "markdown": {
    "content": "【严重】冯校长火锅·玉环店 · 后厨烟雾\n> 时间：14:32\n> 建议：立即到场确认\n\n[打开看板](http://ops.example.com/alerts.html)"
  }
}
```

实现见 `cloud/alert_gateway/gateway.py` · 店级 webhook 配置见 DEV-414。

---

## 9. 文案 QA Checklist

- [ ] 标题含店名，督导多店时不混淆
- [ ] 一句说清「发生了什么」
- [ ] 含可点击深链（店级 dashboard URL）
- [ ] critical 不含营销/冗余词
- [ ] 首月 warn 推手机默认关闭，与店长概念测试一致
- [ ] 22:00~08:00 非 critical 不推（可店级覆盖）

---

## 10. 版本记录

| 版本 | 日期 | 说明 |
|------|------|------|
| V1.0 | 2026-06-15 | 初版：critical/warn/日报/升级/清台五类模板 |
