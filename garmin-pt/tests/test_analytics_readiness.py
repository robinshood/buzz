from datetime import date, timedelta

from garmin_pt.analytics import readiness
from garmin_pt.config import LoadCfg, ReadinessCfg

R = ReadinessCfg()
L = LoadCfg()


def sig(**kw) -> readiness.Signals:
    base = readiness.Signals(
        date="2026-08-31",
        hrv_ms=55.0,
        hrv_baseline_mean=55.0,
        hrv_baseline_sd=5.0,
        hrv_baseline_n=45,
        hrv_z=0.0,
        sleep_h=7.5,
        sleep_score=80,
        short_nights_last2=0,
        acwr=1.0,
    )
    for k, v in kw.items():
        setattr(base, k, v)
    return base


def test_calibrating_gate_at_27_vs_28_nights():
    assert readiness.evaluate(sig(hrv_baseline_n=27), R, L).status == "calibrating"
    assert readiness.evaluate(sig(hrv_baseline_n=28), R, L).status == "ok"


def test_rule_acwr_ceiling_wins_over_everything():
    d = readiness.evaluate(sig(acwr=1.6, hrv_z=-2.0), R, L)
    assert d.recommendation == "forced_easy_week"
    assert d.rules_fired == ["acwr_ceiling"]


def test_rule_hrv_red():
    d = readiness.evaluate(sig(hrv_z=-1.6), R, L)
    assert d.recommendation == "swap_to_easy"
    assert "hrv_red" in d.rules_fired


def test_rule_two_short_nights_alone():
    d = readiness.evaluate(sig(short_nights_last2=2), R, L)
    assert d.recommendation == "swap_to_easy"
    assert d.rules_fired == ["short_sleep"]


def test_rule_hrv_yellow():
    d = readiness.evaluate(sig(hrv_z=-1.0), R, L)
    assert d.recommendation == "reduce_intensity"
    assert d.rules_fired == ["hrv_yellow"]


def test_rule_add_load_requires_low_acwr():
    assert readiness.evaluate(sig(hrv_z=1.5, acwr=0.7), R, L).recommendation == "add_load"
    assert readiness.evaluate(sig(hrv_z=1.5, acwr=1.0), R, L).recommendation == "run_plan"


def test_soreness_downgrades_add_load():
    d = readiness.evaluate(sig(hrv_z=1.5, acwr=0.7, subjective={"soreness": 4}), R, L)
    assert d.recommendation == "run_plan"
    assert "soreness_downgrade" in d.rules_fired


def test_run_plan_default():
    d = readiness.evaluate(sig(), R, L)
    assert d.recommendation == "run_plan"


def test_score_monotonic_in_hrv():
    low = readiness.evaluate(sig(hrv_z=-2.0), R, L).score
    high = readiness.evaluate(sig(hrv_z=2.0, acwr=1.0), R, L).score
    assert low is not None and high is not None and low < high


def test_gather_signals_from_seeded_db(db_conn):
    asof = date(2026, 8, 31)
    # 40 netter baseline: 30×50 + 10×60 rundt dagens dato
    for i in range(1, 41):
        d = (asof - timedelta(days=i)).isoformat()
        hrv = 60.0 if i <= 10 else 50.0
        db_conn.execute(
            "INSERT INTO daily (date, hrv_last_night_avg, resting_hr, sleep_duration_min) "
            "VALUES (?, ?, 47, 430)",
            (d, hrv),
        )
    db_conn.execute(
        "INSERT INTO daily (date, hrv_last_night_avg, resting_hr, sleep_duration_min, "
        "sleep_score, body_battery_high) VALUES (?, 45.0, 52, 330, 60, 55)",
        (asof.isoformat(),),
    )
    db_conn.execute(
        "INSERT INTO subjective (date, sleep_feel, stress, soreness, motivation) "
        "VALUES (?, 2, 4, 3, 3)",
        (asof.isoformat(),),
    )
    s = readiness.gather_signals(db_conn, R, asof)
    assert s.hrv_baseline_n == 40
    assert s.hrv_ms == 45.0
    assert s.hrv_z is not None and s.hrv_z < -1.0
    assert s.short_nights_last2 == 1  # bare i natt var < 6t
    assert s.rhr_dev_bpm is not None and s.rhr_dev_bpm > 4
    assert s.subjective == {"sleep_feel": 2, "stress": 4, "soreness": 3, "motivation": 3}
    d = readiness.evaluate(s, R, L)
    assert d.status == "ok"
    assert d.recommendation in {"swap_to_easy", "reduce_intensity"}
