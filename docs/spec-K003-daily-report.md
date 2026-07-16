# K-003: 废料日报系统 — 自动生成 + Dashboard 推送

> 功能ID: K-003 | 日期: 2026-07-16 | 状态: 实现中

## 1. 概述

基于现有 waste_timeseries 表 + waste_alerts 表，构建数据驱动的废料日报系统。每日 22:00 自动生成结构化日报，推送到 Dashboard 新页面 `daily-report.html`，并支持 API 查询。

与现有 LLM markdown 日报 (`report.html` + `/v1/reports/daily`) 的区别：
| 维度 | K-003 废料日报 | 现有 LLM 日报 |
|------|---------------|---------------|
| 数据源 | waste_timeseries + waste_alerts | Hub store summary |
| 格式 | 结构化 JSON | LLM 生成的 Markdown |
| 可视化 | Dashboard 图表 (SVG趋势/条形图) | 纯文本 markdown |
| 受众 | 店长快速浏览废料KPI | 深度运营分析 |

## 2. API 接口契约

### 2.1 GET /api/daily-report

**请求参数**:
| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| store_id | string | 否 | auth.store_id / store_yuhuan | 门店 ID |
| date | string | 否 | 今日日期 | 日期 YYYY-MM-DD |

**认证**: 需要有效的 AuthContext (与现有 kitchen waste API 一致)

**响应 (200)**:
```json
{
  "store_id": "store_yuhuan",
  "date": "2026-07-16",
  "hero": {
    "total_waste_count": 153,
    "event_count": 8,
    "top_5_skus": [
      {"sku": "毛肚", "count": 45, "pct": 29.4},
      {"sku": "鸭肠", "count": 30, "pct": 19.6}
    ],
    "day_over_day": {
      "today": 153,
      "yesterday": 128,
      "change_pct": 19.5,
      "direction": "up"
    },
    "seven_day_avg": 120.5,
    "thirty_day_avg": 110.3
  },
  "trend_30d": {
    "daily": [
      {"date": "2026-07-01", "total_count": 100, "event_count": 5, "top_skus": [...]}
    ],
    "trend": [100, 95, 110, ...],
    "dates": ["2026-07-01", "2026-07-02", ...]
  },
  "alerts": [
    {
      "id": 1,
      "alert_type": "spike",
      "current_count": 153,
      "baseline_avg": 98.3,
      "ratio": 1.56,
      "message": "废料计数暴增：2026-07-16 共计153件 > 7日均值98.3件 × 1.5，环比+56%",
      "acknowledged": 0,
      "created_at": "2026-07-16T22:00:00+00:00"
    }
  ],
  "generated_at": "2026-07-16T22:00:00+08:00"
}
```

**错误响应**:
| 状态码 | 场景 | body |
|--------|------|------|
| 401 | 未认证 | `{"detail": "Not authenticated"}` |
| 403 | 无门店权限 | `{"detail": "Forbidden"}` |
| 422 | 参数校验失败 | `{"detail": [...]}` |
| 500 | 内部错误 | `{"detail": "Internal server error"}` |

**边界条件**:
- `date` 为今天但尚无数据 → hero 各项为 0/空列表，trend_30d 包含零填充日期
- `date` 为未来日期 → 返回 400 `{"detail": "date cannot be in the future"}`
- store_id 不存在 → 返回 200 但所有数据为空（hero.total_waste_count=0）
- 无 30 天历史数据 → trend 只有已有天数
- top_5_skus 少于 5 → 返回实际数量

**性能预算**: < 100ms (SQLite), < 200ms (PG)

### 2.2 日报自动调度

集成到现有 `DailyReportScheduler` profiles:
- 新增 profile: `waste_daily_report`，kind=`waste_daily`，hour=22, minute=0
- 调度逻辑：调用 `generate_waste_daily_report` 写入 Hub 内存供 Dashboard 拉取

## 3. Dashboard 页面: daily-report.html

### 3.1 页面结构

- 遵循 app-shell 模式 (sidebar + topbar + content)
- 侧边栏高亮 "废料日报"
- 顶部栏: 门店选择 + 日期选择 + 自动刷新按钮

### 3.2 Hero 卡片区 (5列)

| 卡片 | 数据源 | 数字样式 |
|------|--------|---------|
| 📦 今日废料总数 | hero.total_waste_count | brand 色 / 大号 |
| 📋 今日事件数 | hero.event_count | muted |
| 📊 7日均值 | hero.seven_day_avg | ok 色 |
| 📈 日环比 | hero.day_over_day | up=accent / down=ok + 箭头 |
| 🔴 30日均值 | hero.thirty_day_avg | warn 色 |

### 3.3 30天趋势图

- SVG 折线图 (700×200), 复用 `kitchen-count.html` 的 renderLineChart 模式
- X轴: 日期 (MM-DD)
- Y轴: 废料计数
- 三条线: 每日计数(橙红实线) + 7日均线(黄色虚线) + 30日均线(蓝色虚线)

### 3.4 TOP5 废料SKU

- 水平条形图，按 count 降序
- 每行: SKU名 | 进度条 | Count | 占比%
- 复用 kitchen-count.html 的 `.sku-row` 样式

### 3.5 异常告警列表

- 从 `alerts` 数组渲染
- 红色告警条 (未确认) / 灰色 (已确认)
- 显示: 日期 / 告警消息 / 状态标签
- 点击可确认

### 3.6 自动刷新

- 每 5 分钟自动拉取 (300000ms)
- LIVE 状态指示灯

## 4. 代码文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `hotpot_platform/cloud/event_hub/routers/daily_report.py` | **新建** | 日报 API 路由 |
| `hotpot_platform/cloud/event_hub/domain/daily_report.py` | **新建** | 日报数据聚合纯函数 |
| `hotpot_platform/cloud/event_hub/daily_scheduler.py` | **修改** | 新增 waste_daily 调度 profile |
| `hotpot_platform/cloud/event_hub/server.py` | **修改** | 注册 daily_report router |
| `dashboard/daily-report.html` | **新建** | 废料日报 Dashboard 页面 |
| `docs/spec-K003-daily-report.md` | **新建** | 本 spec |
| `docs/test_cases-K003-daily-report.md` | **新建** | 测试用例 |
