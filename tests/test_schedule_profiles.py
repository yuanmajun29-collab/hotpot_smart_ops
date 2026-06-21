"""Schedule profiles for 三时段损耗调度 (LOSS-507).

15:00 备货建议 / 22:00 损耗复盘 / 周一 09:00 损耗趋势周报.
Pure, deterministic tests — inject `now`, no threads/sleep/real clock.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

TZ = "Asia/Shanghai"


def _dt(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(TZ))


def test_due_profiles_matches_hour_minute():
    from cloud.event_hub.daily_scheduler import ScheduleProfile, due_profiles
    profiles = [
        ScheduleProfile("restock", 15, 0, None, "restock"),
        ScheduleProfile("daily_loss", 22, 0, None, "daily"),
    ]
    assert [p.name for p in due_profiles(profiles, _dt(2026, 6, 21, 15, 0))] == ["restock"]
    assert [p.name for p in due_profiles(profiles, _dt(2026, 6, 21, 22, 0))] == ["daily_loss"]
    assert due_profiles(profiles, _dt(2026, 6, 21, 15, 1)) == []


def test_due_profiles_respects_weekday():
    from cloud.event_hub.daily_scheduler import ScheduleProfile, due_profiles
    weekly = ScheduleProfile("weekly", 9, 0, 0, "weekly")  # Monday=0
    assert datetime(2026, 6, 22).weekday() == 0   # Monday
    assert datetime(2026, 6, 21).weekday() == 6   # Sunday
    assert [p.name for p in due_profiles([weekly], _dt(2026, 6, 22, 9, 0))] == ["weekly"]
    assert due_profiles([weekly], _dt(2026, 6, 21, 9, 0)) == []  # Sunday → not due


def test_default_loss_profiles_three_slots():
    from cloud.event_hub.daily_scheduler import default_loss_profiles, validate_profiles
    profs = {p.name: p for p in default_loss_profiles()}
    assert set(profs) == {"restock", "daily_loss", "weekly"}
    assert (profs["restock"].hour, profs["restock"].minute) == (15, 0)
    assert (profs["daily_loss"].hour, profs["daily_loss"].minute) == (22, 0)
    assert (profs["weekly"].hour, profs["weekly"].minute, profs["weekly"].weekday) == (9, 0, 0)
    validate_profiles(list(profs.values()))


def test_validate_profiles_rejects_ambiguous_or_invalid_config():
    from cloud.event_hub.daily_scheduler import ScheduleProfile, validate_profiles

    with pytest.raises(ValueError, match="duplicate"):
        validate_profiles([
            ScheduleProfile("restock", 15, 0),
            ScheduleProfile("restock", 16, 0),
        ])
    with pytest.raises(ValueError, match="hour"):
        validate_profiles([ScheduleProfile("bad", 24, 0)])
    with pytest.raises(ValueError, match="minute"):
        validate_profiles([ScheduleProfile("bad", 15, 60)])
    with pytest.raises(ValueError, match="weekday"):
        validate_profiles([ScheduleProfile("bad", 9, 0, 7)])


def test_run_due_dedups_per_profile_per_store_per_day():
    from cloud.event_hub.daily_scheduler import DailyReportScheduler, ScheduleProfile
    calls = []
    profiles = [
        ScheduleProfile("restock", 15, 0, None, "restock"),
        ScheduleProfile("daily_loss", 22, 0, None, "daily"),
    ]
    dispatch = {
        "restock": lambda sid: calls.append(("restock", sid)),
        "daily": lambda sid: calls.append(("daily", sid)),
    }
    s = DailyReportScheduler(stores=["store_yuhuan"], profiles=profiles, dispatch=dispatch, tz_name=TZ)

    s._run_due(_dt(2026, 6, 21, 15, 0))
    s._run_due(_dt(2026, 6, 21, 15, 0))  # same profile same day → no duplicate
    assert calls == [("restock", "store_yuhuan")]

    s._run_due(_dt(2026, 6, 21, 22, 0))  # different profile same day → fires
    assert calls == [("restock", "store_yuhuan"), ("daily", "store_yuhuan")]

    s._run_due(_dt(2026, 6, 22, 15, 0))  # next day → restock fires again
    assert calls.count(("restock", "store_yuhuan")) == 2


def test_legacy_single_slot_still_works():
    """Backward compat: DailyReportScheduler(generate_fn) keeps the 22:00 daily slot."""
    from cloud.event_hub.daily_scheduler import DailyReportScheduler
    fired = []
    s = DailyReportScheduler(lambda sid, push: fired.append((sid, push)),
                             stores=["store_yuhuan"], hour=22, minute=0, tz_name=TZ)
    s._run_due(_dt(2026, 6, 21, 22, 0))
    s._run_due(_dt(2026, 6, 21, 22, 0))  # dedup same day
    assert fired == [("store_yuhuan", True)]
    s._run_due(_dt(2026, 6, 21, 21, 0))  # wrong hour → nothing
    assert len(fired) == 1
