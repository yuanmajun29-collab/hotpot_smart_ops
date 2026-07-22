"""Tests for tasks 3-5: 废料时序 + 缺斤少两拦截 + 翻台率."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ── Task 3: 废料时序 ──

def test_waste_timeseries_domain():
    """验证 waste_timeseries 领域函数。"""
    from hotpot_platform.cloud.event_hub.domain.waste_timeseries import (
        aggregate_waste_events,
        compute_trend_comparison,
        check_alert,
        format_alert_message,
    )

    # 测试聚合
    events = [
        {
            "payload": {
                "metadata": {
                    "items": [
                        {"sku": "毛肚", "count": 10},
                        {"sku": "鸭肠", "count": 5},
                    ],
                    "total_waste_count": 15,
                }
            }
        }
    ]
    result = aggregate_waste_events(events, "2026-07-23")
    assert result["date"] == "2026-07-23"
    assert result["total_count"] == 15

    # 测试趋势对比
    daily = [
        {"date": "2026-07-01", "total_count": 100, "event_count": 5, "top_skus": []},
        {"date": "2026-07-02", "total_count": 120, "event_count": 6, "top_skus": []},
    ]
    comparison = compute_trend_comparison(daily)
    assert "day_over_day" in comparison

    # 测试告警
    triggered, ratio = check_alert(100, 50)  # 100 vs 50*1.5=75 → triggered
    assert triggered is True
    assert ratio == 2.0

    triggered2, ratio2 = check_alert(50, 50)
    assert triggered2 is False

    # 测试告警消息
    msg = format_alert_message("2026-07-23", 100, 50.0, 2.0)
    assert "暴增" in msg


def test_waste_trend_router_import():
    """验证 waste_trend 路由模块可导入且有 router。"""
    from hotpot_platform.cloud.event_hub.routers.waste_trend import router, record_waste_to_timeseries
    assert router is not None
    assert callable(record_waste_to_timeseries)


def test_waste_trend_write_body():
    """验证 WasteTrendWriteBody 模型。"""
    from hotpot_platform.cloud.event_hub.routers.waste_trend import WasteTrendWriteBody
    body = WasteTrendWriteBody(
        store_id="store_test",
        zone="后厨",
        item_class="毛肚",
        item_count=12,
        estimated_loss_amount=156.0,
    )
    assert body.item_count == 12
    assert body.zone == "后厨"


# ── Task 4: 缺斤少两拦截 ──

def test_weight_thresholds():
    """验证阈值常量。"""
    from hotpot_platform.cloud.event_hub.routers.receiving import (
        WEIGHT_ALERT_THRESHOLD_PCT,
        WEIGHT_REJECT_THRESHOLD_PCT,
    )
    assert WEIGHT_ALERT_THRESHOLD_PCT == 5.0
    assert WEIGHT_REJECT_THRESHOLD_PCT == 10.0


def test_variance_pct():
    """验证方差计算函数。"""
    from hotpot_platform.cloud.event_hub.receiving_store import variance_pct

    # 正常
    assert variance_pct(110, 100) == 10.0
    # 缺斤少两
    assert variance_pct(90, 100) == -10.0
    # 零 PO
    assert variance_pct(100, 0) is None
    # None PO
    assert variance_pct(100, None) is None


def test_supplier_storage_schema_has_supplier_id():
    """验证 receiving 表定义包含 supplier_id。"""
    from hotpot_platform.cloud.event_hub.receiving_store import SQLITE_RECEIVING_SCHEMA
    assert "supplier_id" in SQLITE_RECEIVING_SCHEMA
    assert "idx_receiving_batches_supplier" in SQLITE_RECEIVING_SCHEMA


# ── Task 5: 翻台率 ──

def test_turnover_rate_computation():
    """验证翻台率计算函数。"""
    from hotpot_platform.cloud.event_hub.domain.turnover import compute_turnover_rate

    # 模拟一天的桌态历史
    table_history = {
        "T01": [
            {"status": "occupied", "from_status": "empty", "changed_at": "2026-07-23T10:00:00+00:00", "duration_min": 0.0},
            {"status": "needs_cleaning", "from_status": "occupied", "changed_at": "2026-07-23T11:00:00+00:00", "duration_min": 60.0},
            {"status": "completed", "from_status": "needs_cleaning", "changed_at": "2026-07-23T11:15:00+00:00", "duration_min": 15.0},
            {"status": "occupied", "from_status": "completed", "changed_at": "2026-07-23T12:00:00+00:00", "duration_min": 45.0},
            {"status": "completed", "from_status": "occupied", "changed_at": "2026-07-23T13:00:00+00:00", "duration_min": 60.0},
        ],
        "T02": [
            {"status": "occupied", "from_status": "empty", "changed_at": "2026-07-23T11:00:00+00:00", "duration_min": 0.0},
            {"status": "completed", "from_status": "occupied", "changed_at": "2026-07-23T12:30:00+00:00", "duration_min": 90.0},
        ],
    }

    result = compute_turnover_rate(table_history, total_tables=10, window_hours=24.0)

    # T01 completed 2次, T02 completed 1次 = 3次完成
    # rate = 3 / 10 / 1 = 0.3
    assert result["total_tables"] == 10
    assert result["completed_tables"] == 3
    assert result["turnover_rate"] == 0.3
    assert result["avg_dine_min"] > 0  # 应该算出平均用餐时间


def test_turnover_suggestions_compat():
    """验证 turnover_suggestions 兼容接口仍可用。"""
    from hotpot_platform.cloud.event_hub.domain.turnover import turnover_suggestions

    tables = {
        "T01": {"table_id": "T01", "state": "need_clean"},
        "T02": {"table_id": "T02", "state": "empty"},
        "T03": {"table_id": "T03", "state": "checkout"},
    }
    result = turnover_suggestions(tables)
    assert len(result) == 3
    # need_clean 优先级最高
    assert result[0]["table_id"] == "T01"
    assert result[0]["action"] == "立即清台"


def test_table_history_in_event_store():
    """验证 EventStore 有 table_history 属性。"""
    from hotpot_platform.cloud.event_hub.hub_core import EventStore
    store = EventStore("store_test")
    assert hasattr(store, "table_history")
    assert store.table_history == {}


def test_turnover_rate_system_route():
    """验证 turnover rate 路由在 system.py 中。"""
    system_path = (
        PROJECT_ROOT
        / "hotpot_platform"
        / "cloud"
        / "event_hub"
        / "routers"
        / "system.py"
    )
    content = system_path.read_text()
    assert "/api/v1/turnover/rate" in content
