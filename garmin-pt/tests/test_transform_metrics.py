from datetime import date

from conftest import load_fixture

from garmin_pt.ingest.metrics import metrics_row, week_start_of, weekly_aggregates


def test_week_start_of():
    assert week_start_of(date(2026, 8, 31)) == date(2026, 8, 31)  # mandag
    assert week_start_of(date(2026, 9, 6)) == date(2026, 8, 31)  # søndag


def test_metrics_row_from_fixtures():
    row = metrics_row(
        date(2026, 8, 24),
        training_status=load_fixture("training_status.json"),
        max_metrics=load_fixture("max_metrics.json"),
    )
    assert row == {
        "week_start": "2026-08-24",
        "vo2max": 52.3,
        "training_status": "PRODUCTIVE",
        "threshold_hr": 168,
    }


def test_metrics_row_all_missing():
    row = metrics_row(date(2026, 8, 24), None, None)
    assert row["vo2max"] is None
    assert row["training_status"] is None
    assert row["threshold_hr"] is None


def test_weekly_aggregates(db_conn):
    ws = date(2026, 8, 24)
    for i, (d, trimp) in enumerate(
        [("2026-08-24", 100.0), ("2026-08-26", 60.0), ("2026-08-29", 80.0)]
    ):
        db_conn.execute(
            "INSERT INTO activities (activity_id, date, activity_type, trimp) "
            "VALUES (?, ?, 'running', ?)",
            (i + 1, d, trimp),
        )
    db_conn.execute(
        "INSERT INTO daily (date, resting_hr, weight_kg) VALUES ('2026-08-25', 46, 82.0)"
    )
    db_conn.execute(
        "INSERT INTO daily (date, resting_hr, weight_kg) VALUES ('2026-08-27', 48, 82.6)"
    )
    agg = weekly_aggregates(db_conn, ws)
    assert agg["weekly_trimp"] == 240.0
    assert agg["resting_hr_avg"] == 47.0
    assert agg["weight_avg_kg"] == 82.3
    # < 14 dagers historikk → ACWR kalibrerer
    assert agg["acwr"] is None
