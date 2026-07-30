# K-002 趋势预警 — 接口契约

> 功能ID: K-002 | 日期: 2026-07-16 | 版本: v1

## 一、功能描述

后厨损耗趋势预警：基于废料计数时序数据，提供每日趋势查询、同比/环比对比，以及异常检测告警。

**输入**: Edge端推送的废料事件（`event_type: vlm_waste_estimate`）中的计数数据  
**输出**: 30天趋势 + 同比/环比 + 自动告警

## 二、数据模型

### 2.1 waste_timeseries 表

```sql
CREATE TABLE IF NOT EXISTS waste_timeseries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id TEXT NOT NULL,
    date TEXT NOT NULL,              -- YYYY-MM-DD
    total_count INTEGER NOT NULL DEFAULT 0,
    event_count INTEGER NOT NULL DEFAULT 0,
    top_skus TEXT NOT NULL DEFAULT '[]',  -- JSON array: [{"sku":"毛肚","count":12},...]
    generated_at TEXT NOT NULL,
    UNIQUE(store_id, date)
);
CREATE INDEX IF NOT EXISTS idx_wts_store_date ON waste_timeseries(store_id, date DESC);
```

### 2.2 waste_alerts 表（告警持久化）

```sql
CREATE TABLE IF NOT EXISTS waste_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id TEXT NOT NULL,
    date TEXT NOT NULL,
    alert_type TEXT NOT NULL,        -- 'spike' (日环比暴增)
    current_count INTEGER NOT NULL,
    baseline_avg REAL NOT NULL,
    ratio REAL NOT NULL,             -- current_count / baseline_avg
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    acknowledged INTEGER NOT NULL DEFAULT 0
);
```

## 三、API 契约

### 3.1 GET /api/kitchen/waste/trend

**Query参数**:
- `store_id` (string, optional): 门店ID，默认当前门店
- `days` (int, optional, default=30, range 1-90): 查询天数
- `include_compare` (bool, optional, default=true): 是否包含同比/环比

**响应 (200)**:
```json
{
  "store_id": "store_yuhuan",
  "days": 30,
  "daily": [
    {
      "date": "2026-07-16",
      "total_count": 153,
      "event_count": 8,
      "top_skus": [{"sku": "毛肚", "count": 45}, {"sku": "鸭肠", "count": 30}]
    }
  ],
  "trend": [153, 128, ...],           // 每日 total_count，与 dates 一一对应
  "dates": ["2026-07-01", "2026-07-02", ...],
  "comparison": {
    "week_over_week": {               // 周环比：最近7天 vs 上周同7天
      "current_avg": 145.3,
      "previous_avg": 128.1,
      "change_pct": 13.4,
      "direction": "up"
    },
    "day_over_day": {                 // 日环比：今天 vs 昨天
      "today": 153,
      "yesterday": 128,
      "change_pct": 19.5,
      "direction": "up"
    },
    "thirty_day_avg": 132.5,          // 30日移动均值
    "seven_day_avg": 140.7            // 7日移动均值
  },
  "generated_at": "2026-07-16T15:30:00+00:00"
}
```

**异常边界**:
- `store_id` 不存在 → `404 {"detail": "Store not found: <store_id>"}`
- `days < 1 or days > 90` → `422` (Query validation)
- 数据库无数据 → `200` 但 daily 全为0填充

**延迟预算**: < 200ms (SQLite 单表聚合)

### 3.2 GET /api/kitchen/waste/alerts

**Query参数**:
- `store_id` (string, optional): 门店ID
- `days` (int, optional, default=7): 查询最近N天的告警

**响应 (200)**:
```json
{
  "store_id": "store_yuhuan",
  "alerts": [
    {
      "id": 1,
      "date": "2026-07-16",
      "alert_type": "spike",
      "current_count": 153,
      "baseline_avg": 98.3,
      "ratio": 1.56,
      "message": "废料计数暴增：今日153件 > 7日均值98.3件×1.5，环比+56%",
      "created_at": "2026-07-16T22:00:00+00:00",
      "acknowledged": false
    }
  ],
  "count": 1
}
```

### 3.3 POST /api/kitchen/waste/alerts/check

**触发告警检查**（也可由定时任务/pipeline触发）

**Query参数**:
- `store_id` (string, optional)

**Body (optional)**:
```json
{
  "date": "2026-07-16",
  "current_count": 153
}
```
若不传 body，则从 waste_timeseries 表中查询今日数据。

**响应 (200)**:
```json
{
  "store_id": "store_yuhuan",
  "date": "2026-07-16",
  "alert_triggered": true,
  "current_count": 153,
  "seven_day_avg": 98.3,
  "ratio": 1.56,
  "threshold": 1.5,
  "alert_id": 5
}
```

**告警规则**: `current_count > seven_day_avg * 1.5` 且 `seven_day_avg > 0`

### 3.4 POST /api/kitchen/waste/alerts/{alert_id}/ack

**标记告警已确认**

**响应**: `200 {"ok": true, "alert_id": 5}`  
**404**: 告警不存在

## 四、对比基准规则

| 指标 | 计算公式 | 说明 |
|------|---------|------|
| 日环比 | (today - yesterday) / yesterday × 100 | 昨日无数据时返回 null |
| 周环比 | (avg[最近7天] - avg[前7天]) / avg[前7天] × 100 | 不足14天数据时返回 null |
| 7日均值 | avg[最近7天非零日] | 全部为0时返回0 |
| 30日均值 | avg[最近30天非零日] | 同上 |
| 告警阈值 | current > 7d_avg × 1.5 | 7d_avg为0时不触发 |

## 五、扩展点（P2）

- 同比（去年同期）：需至少1年数据，当前阶段不实现
- 时序预测模型（替换简单阈值）：P2阶段
- 告警聚合（连续N天暴增 → 升级为P0）：P2阶段
