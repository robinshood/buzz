from conftest import load_fixture

from garmin_pt.ingest.daily import daily_row


def test_full_day():
    row = daily_row(
        "2026-08-30",
        hrv=load_fixture("hrv_day.json"),
        sleep=load_fixture("sleep_day.json"),
        rhr=load_fixture("rhr_day.json"),
        summary=load_fixture("user_summary.json"),
        weigh_ins=load_fixture("weigh_ins.json"),
    )
    assert row == {
        "date": "2026-08-30",
        "hrv_last_night_avg": 48,
        "hrv_status": "BALANCED",
        "sleep_score": 78,
        "sleep_duration_min": 450.0,
        "sleep_deep_min": 90.0,
        "sleep_rem_min": 100.0,
        "sleep_light_min": 240.0,
        "sleep_awake_min": 20.0,
        "resting_hr": 47,
        "body_battery_high": 82,
        "body_battery_low": 21,
        "stress_avg": 27,
        "steps": 9432,
        "weight_kg": 82.4,
    }


def test_hrv_missing_night():
    row = daily_row(
        "2026-08-30",
        hrv=load_fixture("hrv_day_missing.json"),
        sleep=load_fixture("sleep_day_short.json"),
        rhr=None,
        summary=None,
        weigh_ins=None,
    )
    assert row["hrv_last_night_avg"] is None
    assert row["hrv_status"] is None
    assert row["sleep_duration_min"] == 330.0  # 5,5 t — kort natt
    assert row["resting_hr"] == 51  # fallback fra søvn-payloaden
    assert row["weight_kg"] is None


def test_all_payloads_none():
    row = daily_row("2026-08-30", None, None, None, None, None)
    assert row["date"] == "2026-08-30"
    assert all(v is None for k, v in row.items() if k != "date")
