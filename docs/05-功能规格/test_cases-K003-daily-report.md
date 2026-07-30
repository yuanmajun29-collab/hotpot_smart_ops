# K-003 废料日报系统 测试用例

> 基于 spec-K003-daily-report.md

## 一、API 测试

### T-01: 正常查询 (有数据)
- **请求**: `GET /api/daily-report?store_id=store_yuhuan&date=2026-07-16`
- **前置**: waste_timeseries 表有 2026-07-16 的数据 (total_count=153, event_count=8)
- **预期**: 200，hero.total_waste_count=153，hero.event_count=8，trend_30d 含 30 天数据

### T-02: 正常查询 (无数据日期)
- **请求**: `GET /api/daily-report?store_id=store_yuhuan&date=2026-07-01`
- **前置**: waste_timeseries 表无 2026-07-01 数据
- **预期**: 200，hero.total_waste_count=0，hero.top_5_skus=[]，trend_30d 中该日为零填充

### T-03: 缺参数 (使用默认)
- **请求**: `GET /api/daily-report` (无 store_id, 无 date)
- **预期**: 200，store_id = auth.store_id 或默认 store_yuhuan，date = 今日

### T-04: 未来日期
- **请求**: `GET /api/daily-report?store_id=store_yuhuan&date=2099-01-01`
- **预期**: 400，错误信息 "date cannot be in the future"

### T-05: 无效日期格式
- **请求**: `GET /api/daily-report?store_id=store_yuhuan&date=not-a-date`
- **预期**: 422 或 400

### T-06: 不存在门店
- **请求**: `GET /api/daily-report?store_id=nonexistent_store`
- **预期**: 200，hero 全部为 0/空

### T-07: 无认证
- **请求**: `GET /api/daily-report` (不带 auth header)
- **预期**: 401

### T-08: 告警数据
- **请求**: `GET /api/daily-report?store_id=store_yuhuan&date=2026-07-16`
- **前置**: waste_alerts 表有一条未确认告警
- **预期**: 200，alerts 数组包含该告警，包含 id/message/acknowledged

### T-09: 日环比 (up)
- **前置**: 今日 count=153, 昨日 count=128
- **预期**: hero.day_over_day.change_pct=19.5, direction="up"

### T-10: 日环比 (down)
- **前置**: 今日 count=100, 昨日 count=150
- **预期**: hero.day_over_day.change_pct=-33.3, direction="down"

### T-11: 日环比 (flat)
- **前置**: 今日 count=0, 昨日 count=0
- **预期**: hero.day_over_day.change_pct=0.0, direction="flat"

### T-12: TOP5 SKU 占比
- **前置**: top_skus 有 10 个 SKU
- **预期**: top_5_skus 返回前 5 个，每个包含 pct (占总数的百分比)

### T-13: 性能
- **请求**: `GET /api/daily-report?store_id=store_yuhuan`
- **预期**: 响应时间 < 200ms

## 二、Dashboard 测试

### T-14: 页面可访问
- **操作**: 浏览器访问 `http://localhost:3000/daily-report.html`
- **预期**: HTTP 200，页面渲染无 JS 错误

### T-15: Hero 卡片渲染
- **前置**: API 返回 hero 数据
- **预期**: 5 个 hero 卡片正确显示数字/颜色/环比箭头

### T-16: 趋势图渲染
- **前置**: API 返回 30 天 trend 数据
- **预期**: SVG 折线图显示，含 7日/30日均线

### T-17: TOP5 SKU 渲染
- **前置**: API 返回 top_5_skus
- **预期**: 5 条 SKU 行，带进度条和占比

### T-18: 告警列表渲染
- **前置**: API 返回 alerts
- **预期**: 告警条显示，未确认红色/已确认灰色

### T-19: 自动刷新
- **操作**: 等待 5 分钟
- **预期**: LIVE 指示灯显示，数据自动更新

### T-20: 门店切换
- **操作**: 切换门店下拉
- **预期**: 页面重新加载对应门店数据

### T-21: 日期选择
- **操作**: 选择历史日期
- **预期**: 显示该日期的历史日报数据

### T-22: 无数据状态
- **前置**: 选定日期无数据
- **预期**: Hero 显示 0，图表无数据时展示空状态提示

## 三、调度集成测试

### T-23: 调度 Profile 注册
- **操作**: DailyReportScheduler 启动
- **预期**: profiles 包含 waste_daily_report @ 22:00

### T-24: 自动触发
- **操作**: 系统时间到达 22:00
- **预期**: waste_daily handler 被执行，日报数据写入

### T-25: 幂等性
- **操作**: 同一分钟内多次触发
- **预期**: 只执行一次 (通过 _last_run_date 去重)
