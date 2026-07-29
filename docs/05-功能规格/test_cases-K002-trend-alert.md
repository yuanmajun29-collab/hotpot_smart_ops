# K-002 趋势预警 — 测试用例

> 关联 spec: docs/spec-K002-trend-alert.md | 版本: v1

## 一、白盒测试

### T-01: waste_timeseries 表创建
- **预期**: `waste_timeseries` 表和 `waste_alerts` 表在 Hub 启动时自动创建
- **验证**: 查询 `sqlite_master` 确认两表存在，包含 UNIQUE(store_id, date) 约束

### T-02: 时序数据写入
- **输入**: 插入一条 `store_yuhuan / 2026-07-16 / total_count=153`
- **预期**: 写入成功，重复插入同 (store_id, date) 自动 `UPSERT` 更新
- **验证**: 查询返回最新 total_count

### T-03: 空数据集趋势查询
- **输入**: GET /api/kitchen/waste/trend?store_id=empty_store&days=30
- **预期**: 返回 200，daily 包含30天全0填充，trend 全为0，comparison 中 change_pct 为 null

### T-04: 日环比计算
- **数据**: today=153, yesterday=128
- **预期**: change_pct≈19.5%, direction="up"
- **数据**: today=80, yesterday=128
- **预期**: change_pct≈-37.5%, direction="down"

### T-05: 周环比计算
- **数据**: 最近7天 avg=145.3, 前7天 avg=128.1
- **预期**: change_pct≈13.4%, direction="up"

### T-06: 告警触发规则
- **数据**: current_count=153, seven_day_avg=98.3
- **预期**: 153 > 98.3 × 1.5 = 147.45, alert_triggered=true, ratio≈1.56
- **数据**: current_count=120, seven_day_avg=98.3
- **预期**: 120 < 147.45, alert_triggered=false

### T-07: 告警边界条件
- **数据**: seven_day_avg=0 (无历史数据)
- **预期**: 不触发告警（避免启动阶段误报）
- **数据**: current_count=0
- **预期**: 不触发告警

### T-08: 告警幂等性
- **预期**: 同一天同一门店重复调用 check，只创建1条告警（按 store_id+date+alert_type 去重）

## 二、黑盒测试

### T-09: API 参数验证
- `days=-1` → 422
- `days=0` → 422
- `days=100` → 422
- `days=30` → 200

### T-10: store_id 不存在
- `store_id=nonexistent` → 仍返回 200（空数据，不报错），daily 全0填充

### T-11: 告警确认
- `POST /api/kitchen/waste/alerts/999/ack` → 404
- `POST /api/kitchen/waste/alerts/{valid_id}/ack` → 200, acknowledged 变为 1

### T-12: 数据库迁移兼容
- **前提**: 已有 events 表中有旧数据
- **预期**: 新代码不破坏现有 events / hub.db 结构，启动正常

## 三、E2E 测试

### T-13: 完整数据流
1. 向 Hub POST vlm_waste_estimate 事件
2. 触发 waste_timeseries 聚合写入（每日收盘/事件推送时触发）
3. GET /api/kitchen/waste/trend 返回最新数据
4. POST /api/kitchen/waste/alerts/check 基于最新数据判定告警
5. Dashboard 页面加载趋势卡片

### T-14: Dashboard 页面渲染
- kitchen-count.html 访问 `http://localhost:3000/kitchen-count.html` → HTTP 200
- 页面包含30天趋势折线图
- 页面包含告警指示灯（当有告警时高亮）
- 页面包含日环比/周环比数据卡片

## 四、非功能测试

### T-15: 性能
- `/api/kitchen/waste/trend` 响应时间 < 200ms (30天数据)
- `/api/kitchen/waste/alerts/check` 响应时间 < 100ms

### T-16: 并发安全
- SQLite 写操作使用 HubDatabase._lock 保护

### T-17: 代码入侵度
- 不新增独立服务，所有代码在 `hotpot_platform/cloud/event_hub/` 下
- 路由通过 `routers/__init__.py` 自动发现
