from datetime import date, timedelta

from garmin_pt.analytics import load


def test_edwards_trimp_known_value():
    # 10 min z1 + 20 min z2 + 5 min z5 → 1*10 + 2*20 + 5*5 = 75
    assert load.edwards_trimp([600, 1200, None, None, 300]) == 75.0


def test_edwards_trimp_no_data():
    assert load.edwards_trimp([None] * 5) is None
    assert load.edwards_trimp([]) is None


def test_activity_trimp_fallback_chain():
    assert load.activity_trimp([600, None, None, None, None], 99.0, 3600)[1] == "edwards"
    assert load.activity_trimp([None] * 5, 99.0, 3600) == (99.0, "garmin_load")
    assert load.activity_trimp([None] * 5, None, 3600) == (60.0, "duration_floor")
    assert load.activity_trimp([None] * 5, None, None) == (None, "none")


def test_acwr_hand_computed():
    asof = date(2026, 8, 31)
    # 28 dager med 50/dag, siste 7 dager 100/dag
    trimp = {asof - timedelta(days=i): (100.0 if i < 7 else 50.0) for i in range(28)}
    # akutt = 700; kronisk = (700 + 21*50)/4 = 437.5 → 1.6
    assert load.acwr(trimp, asof) == 1.6


def test_acwr_needs_14_days_history():
    asof = date(2026, 8, 31)
    trimp = {asof - timedelta(days=i): 50.0 for i in range(10)}
    assert load.acwr(trimp, asof) is None


def test_monotony_hand_computed():
    # mean=50, sample-stdev=40.82 for [50,100,0,50,100,0,50] → 50/40.82 = 1.22
    series = [50.0, 100.0, 0.0, 50.0, 100.0, 0.0, 50.0]
    assert load.monotony(series) == 1.22


def test_monotony_uniform_week_is_none():
    assert load.monotony([50.0] * 7) is None
    assert load.monotony([0.0] * 7) is None


def test_weekly_load_groups_by_monday(db_conn):
    rows = [
        # man 2026-08-24 og søn 2026-08-30 → samme uke; man 2026-08-31 → neste
        (1, "2026-08-24", "running", 3600, 100.0, 600),
        (2, "2026-08-30", "strength_training", 1800, 30.0, None),
        (3, "2026-08-31", "running", 3600, 90.0, 1200),
    ]
    for aid, d, typ, dur, trimp, z2 in rows:
        db_conn.execute(
            "INSERT INTO activities (activity_id, date, activity_type, duration_s, "
            "trimp, hr_zone_2_s) VALUES (?, ?, ?, ?, ?, ?)",
            (aid, d, typ, dur, trimp, z2),
        )
    weeks = load.weekly_load(db_conn, weeks=4, asof=date(2026, 8, 31))
    assert [w["week_start"] for w in weeks] == ["2026-08-31", "2026-08-24"]
    assert weeks[1]["sessions"] == 2
    assert weeks[1]["trimp"] == 130
    assert weeks[0]["zone_minutes"][1] == 20
