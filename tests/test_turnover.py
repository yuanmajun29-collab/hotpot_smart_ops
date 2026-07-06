"""F-T03 翻台优先建议: domain turnover_suggestions ordering and labels."""

from __future__ import annotations

from hotpot_platform.cloud.event_hub.domain.turnover import turnover_suggestions


def test_turnover_priority_ordering_and_actions():
    tables = {
        "T1": {"table_id": "T1", "state": "empty"},
        "T2": {"table_id": "T2", "state": "need_clean"},
        "T3": {"table_id": "T3", "state": "checkout"},
        "T4": {"table_id": "T4", "state": "dining"},  # not actionable -> excluded
    }
    out = turnover_suggestions(tables)

    # need_clean(1) < checkout(2) < empty(3); dining excluded
    assert [x["table_id"] for x in out] == ["T2", "T3", "T1"]
    assert out[0]["state"] == "need_clean"
    assert out[0]["action"] == "立即清台"
    assert out[1]["action"] == "引导结账"
    assert out[2]["action"] == "可安排入座"
    assert all(x["state"] != "dining" for x in out)


def test_turnover_same_priority_sorted_by_table_id():
    tables = {
        "T9": {"table_id": "T9", "state": "need_clean"},
        "T1": {"table_id": "T1", "state": "need_clean"},
    }
    out = turnover_suggestions(tables)
    assert [x["table_id"] for x in out] == ["T1", "T9"]


def test_turnover_empty_input():
    assert turnover_suggestions({}) == []
