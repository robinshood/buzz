from datetime import date, timedelta

from garmin_pt.analytics import strengthprog
from garmin_pt.config import E1rmCfg

CFG = E1rmCfg()


def test_epley_known_value():
    assert strengthprog.epley(80.0, 5) == 93.3
    assert strengthprog.epley(100.0, 1) == 103.3


def test_epley_degrades_on_missing_or_high_reps():
    assert strengthprog.epley(None, 5) is None
    assert strengthprog.epley(80.0, None) is None
    assert strengthprog.epley(80.0, 0) is None
    assert strengthprog.epley(80.0, 13) is None  # over epley_max_reps-taket


def _seed_sets(conn, asof, weeks=6, weight_start=80.0, kg_per_week=1.0):
    """Én benkpressøkt per uke med stigende vekt; 20 % av settene mangler vekt."""
    aid = 100
    for w in range(weeks):
        d = asof - timedelta(days=7 * (weeks - 1 - w))
        aid += 1
        conn.execute(
            "INSERT INTO activities (activity_id, date, activity_type) "
            "VALUES (?, ?, 'strength_training')",
            (aid, d.isoformat()),
        )
        weight = weight_start + kg_per_week * w
        for s in range(1, 6):
            has_weight = s != 5  # siste sett mangler vekt (klokke-realitet)
            conn.execute(
                "INSERT INTO strength_sets (activity_id, date, exercise, muscle_group, "
                "set_index, reps, weight_kg, e1rm, source) "
                "VALUES (?, ?, 'BENCH_PRESS', 'chest', ?, 5, ?, ?, 'garmin')",
                (
                    aid,
                    d.isoformat(),
                    s,
                    weight if has_weight else None,
                    strengthprog.epley(weight, 5) if has_weight else None,
                ),
            )
    return aid


def test_progression_trend_and_data_basis(db_conn):
    asof = date(2026, 8, 31)
    _seed_sets(db_conn, asof)
    out = strengthprog.progression(db_conn, CFG, asof, muscle_group="chest")
    assert len(out["exercises"]) == 1
    ex = out["exercises"][0]
    assert ex["exercise"] == "BENCH_PRESS"
    assert ex["e1rm_last"] > ex["e1rm_first"]
    assert ex["e1rm_slope_kg_per_week"] is not None
    assert 0.8 < ex["e1rm_slope_kg_per_week"] < 1.5  # ~1 kg/uke × Epley-faktor
    assert "80 % med vekt+reps" in ex["data_basis"]
    assert ex["volume_trend"] in {"up", "flat"}


def test_progression_too_few_weeks_reports_note(db_conn):
    asof = date(2026, 8, 31)
    _seed_sets(db_conn, asof, weeks=2)
    out = strengthprog.progression(db_conn, CFG, asof)
    ex = out["exercises"][0]
    assert ex["e1rm_slope_kg_per_week"] is None
    assert "for få uker" in ex["note"]


def test_progression_excludes_superseded(db_conn):
    asof = date(2026, 8, 31)
    aid = _seed_sets(db_conn, asof, weeks=3)
    db_conn.execute("UPDATE strength_sets SET superseded = 1 WHERE activity_id = ?", (aid,))
    out = strengthprog.progression(db_conn, CFG, asof)
    # siste ukes 5 sett borte: 3 uker × 5 - 5 = 10
    assert out["total_sets"] == 10
