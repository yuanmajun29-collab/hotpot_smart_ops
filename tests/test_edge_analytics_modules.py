"""Tests for Edge turnover analyzer and SOP scorer."""

from __future__ import annotations


def test_turnover_analyzer_tracks_sessions_and_anomaly():
    from edge.common.turnover_analyzer import TurnoverAnalyzer

    analyzer = TurnoverAnalyzer(store_id="store_yuhuan", total_tables=2)
    analyzer.process_events(
        [
            {"table_id": "T01", "state": "empty", "timestamp": "2026-07-23T09:50:00+00:00"},
            {"table_id": "T01", "state": "dining", "timestamp": "2026-07-23T10:00:00+00:00"},
            {"table_id": "T01", "state": "needs_cleaning", "timestamp": "2026-07-23T11:00:00+00:00"},
            {"table_id": "T01", "state": "empty", "timestamp": "2026-07-23T11:10:00+00:00"},
            {"table_id": "T02", "state": "dining", "timestamp": "2026-07-23T10:30:00+00:00"},
        ]
    )

    stats = analyzer.aggregate(
        now="2026-07-23T12:00:00+00:00",
        historical_daily_rates={
            "2026-07-22": 1.0,
            "2026-07-21": 1.0,
            "2026-07-20": 1.0,
            "2026-07-19": 1.0,
            "2026-07-18": 1.0,
            "2026-07-17": 1.0,
            "2026-07-16": 1.0,
        },
    )

    assert stats["completed_sessions_today"] == 1
    assert stats["daily_turnover_rate"] == 0.5
    assert stats["avg_dining_duration_min"] == 60.0
    assert stats["avg_cleaning_duration_min"] == 10.0
    assert stats["anomaly"]["drop_pct"] == 50.0


def test_sop_scorer_reads_sop_infer_result_and_tracks_trend():
    from edge.common.sop_scorer import SopScorer

    scorer = SopScorer(store_id="store_yuhuan")
    scorer.record_violation(
        {
            "store_id": "store_yuhuan",
            "station_id": "sop_broth",
            "type": "no_hat",
            "severity": "major",
            "timestamp": "2026-07-22T10:00:00+00:00",
        }
    )
    day1 = scorer.daily_scorecard(day="2026-07-22")

    scorer.record_sop_infer_result(
        {
            "store_id": "store_yuhuan",
            "station_id": "sop_broth",
            "timestamp": "2026-07-23T10:00:00+00:00",
            "violations": [
                {"type": "no_mask", "severity": "critical"},
                {"type": "no_gloves", "severity": "minor"},
            ],
        }
    )
    day2 = scorer.daily_scorecard(day="2026-07-23")

    assert day1["score"] == 90
    assert day2["score"] == 72
    assert day2["severity_counts"] == {"critical": 1, "major": 0, "minor": 1}
    assert day2["trend"]["status"] == "worsening"
