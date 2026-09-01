"""De 8 MCP-verktøyene testes som rene funksjoner mot en seedet database
(GARMIN_PT_DATA_DIR pekes til tmp). Ingen nettverk — push-testene bruker
FakeGarminClient via monkeypatching av auth.login."""

import asyncio
from datetime import date, timedelta

import pytest

from garmin_pt import db, mcp_server
from garmin_pt.analytics.strengthprog import epley

TODAY = date.today()


@pytest.fixture
def data_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GARMIN_PT_DATA_DIR", str(tmp_path / "data"))
    from garmin_pt.config import load_settings

    return load_settings()


def _seed_daily(conn, nights=45, today_hrv=45.0):
    for i in range(nights, 0, -1):
        d = (TODAY - timedelta(days=i)).isoformat()
        hrv = 60.0 if i % 4 == 0 else 54.0
        conn.execute(
            "INSERT INTO daily (date, hrv_last_night_avg, resting_hr, sleep_score, "
            "sleep_duration_min, body_battery_high, weight_kg) "
            "VALUES (?, ?, 46, 78, 440, 80, ?)",
            (d, hrv, 82.0 + (i % 3) * 0.2),
        )
    conn.execute(
        "INSERT INTO daily (date, hrv_last_night_avg, resting_hr, sleep_score, "
        "sleep_duration_min, body_battery_high) VALUES (?, ?, 51, 62, 350, 58)",
        (TODAY.isoformat(), today_hrv),
    )


def _seed_activities(conn, weeks=5):
    aid = 0
    for w in range(weeks):
        monday = TODAY - timedelta(days=TODAY.weekday() + 7 * w)
        for offset, typ, trimp, dur in (
            (0, "running", 150.0, 3600),
            (2, "strength_training", 55.0, 3000),
            (4, "running", 95.0, 2700),
        ):
            d = monday + timedelta(days=offset)
            if d > TODAY:
                continue
            aid += 1
            conn.execute(
                "INSERT INTO activities (activity_id, date, start_time, activity_type, "
                "name, duration_s, trimp, avg_hr, hr_zone_2_s) "
                "VALUES (?, ?, ?, ?, 'økt', ?, ?, 140, 1800)",
                (aid, d.isoformat(), f"{d} 17:00:00", typ, dur, trimp),
            )
    return aid


def _seed_strength(conn, weeks=5):
    aid = 1000
    for w in range(weeks):
        d = TODAY - timedelta(days=7 * w + 1)
        aid += 1
        conn.execute(
            "INSERT INTO activities (activity_id, date, activity_type) "
            "VALUES (?, ?, 'strength_training')",
            (aid, d.isoformat()),
        )
        weight = 84.0 - w  # nyeste uke tyngst
        for s in range(1, 4):
            conn.execute(
                "INSERT INTO strength_sets (activity_id, date, exercise, muscle_group, "
                "set_index, reps, weight_kg, e1rm, source) "
                "VALUES (?, ?, 'BENCH_PRESS', 'chest', ?, 5, ?, ?, 'garmin')",
                (aid, d.isoformat(), s, weight, epley(weight, 5)),
            )
    return aid


def test_all_eight_tools_registered():
    tools = asyncio.run(mcp_server.mcp.list_tools())
    assert {t.name for t in tools} == {
        "get_readiness",
        "get_training_load",
        "get_strength_progression",
        "get_recent_sessions",
        "get_fitness_markers",
        "log_subjective",
        "log_strength_session",
        "push_workout_to_garmin",
    }


def test_read_tools_without_db_return_no_data(data_env):
    for fn in (
        mcp_server.get_readiness,
        mcp_server.get_training_load,
        mcp_server.get_strength_progression,
        mcp_server.get_recent_sessions,
        mcp_server.get_fitness_markers,
    ):
        out = fn()
        assert out["status"] == "no_data"
        assert "garmin-pt ingest" in out["conclusion"]


def test_readiness_calibrating_with_thin_baseline(data_env):
    conn = db.connect(data_env.db_path)
    _seed_daily(conn, nights=10)
    conn.commit()
    conn.close()
    out = mcp_server.get_readiness()
    assert out["status"] == "calibrating"
    assert out["recommendation"] == "calibrating"
    assert out["readiness_score"] is None


def test_readiness_with_low_hrv_today(data_env):
    conn = db.connect(data_env.db_path)
    _seed_daily(conn, nights=45, today_hrv=45.0)
    conn.execute(
        "INSERT INTO subjective (date, sleep_feel, stress, soreness, motivation) "
        "VALUES (?, 2, 4, 3, 3)",
        (TODAY.isoformat(),),
    )
    conn.commit()
    conn.close()
    out = mcp_server.get_readiness()
    assert out["status"] == "ok"
    assert out["recommendation"] in {"swap_to_easy", "reduce_intensity"}
    assert "45 netter HRV" in out["data_basis"]
    assert "subjektiv rapport fra i dag" in out["data_basis"]
    assert out["signals"]["hrv_z"] < -0.5
    assert isinstance(out["conclusion"], str) and "HRV" in out["conclusion"]


def test_training_load(data_env):
    conn = db.connect(data_env.db_path)
    _seed_activities(conn)
    conn.commit()
    conn.close()
    out = mcp_server.get_training_load(weeks=4)
    assert out["weekly"], "forventet minst én ukerad"
    assert out["acwr"] is not None
    assert out["acwr_flag"] in {"ok", "low", "too_high"}
    assert "økter siste 4 uker" in out["conclusion"]
    assert all(len(w["zone_minutes"]) == 5 for w in out["weekly"])


def test_strength_progression(data_env):
    conn = db.connect(data_env.db_path)
    _seed_strength(conn)
    conn.commit()
    conn.close()
    out = mcp_server.get_strength_progression(muscle_group="chest")
    assert len(out["exercises"]) == 1
    ex = out["exercises"][0]
    assert ex["exercise"] == "BENCH_PRESS"
    assert ex["e1rm_slope_kg_per_week"] > 0
    assert "BENCH_PRESS" in out["conclusion"]
    assert "sett siste 12 uker" in out["data_basis"]


def test_recent_sessions_with_and_without_plan(data_env):
    conn = db.connect(data_env.db_path)
    aid = _seed_activities(conn, weeks=2)
    row = conn.execute(
        "SELECT date, activity_type FROM activities ORDER BY date DESC LIMIT 1"
    ).fetchone()
    conn.execute(
        "INSERT INTO plan (date, planned_type) VALUES (?, ?)",
        (row["date"], row["activity_type"]),
    )
    conn.commit()
    conn.close()
    out = mcp_server.get_recent_sessions(n=5)
    assert out["sessions"]
    devs = {s["deviation"] for s in out["sessions"]}
    assert "utført som planlagt" in devs
    assert "ingen plan registrert" in devs
    assert aid >= len(out["sessions"])


def test_fitness_markers(data_env):
    conn = db.connect(data_env.db_path)
    _seed_daily(conn, nights=30)
    for w in range(14, -1, -1):
        ws = TODAY - timedelta(days=TODAY.weekday() + 7 * w)
        conn.execute(
            "INSERT OR REPLACE INTO metrics (week_start, vo2max, training_status, threshold_hr) "
            "VALUES (?, ?, 'PRODUCTIVE', 168)",
            (ws.isoformat(), 50.0 + (14 - w) * 0.2),
        )
    conn.commit()
    conn.close()
    out = mcp_server.get_fitness_markers()
    assert out["vo2max"]["current"] == 52.8
    assert out["vo2max"]["delta_90d"] is not None
    assert out["threshold_hr"] == 168
    assert out["training_status"] == "PRODUCTIVE"
    assert "VO2max" in out["conclusion"]


def test_log_subjective_and_streak(data_env):
    out1 = mcp_server.log_subjective(3, 2, 2, 4)
    assert out1["streak_days"] == 1
    assert out1["stored"]["date"] == TODAY.isoformat()
    # idempotent oppdatering samme dag
    out2 = mcp_server.log_subjective(4, 2, 2, 4)
    assert out2["streak_days"] == 1
    conn = db.connect(data_env.db_path, read_only=True)
    assert conn.execute("SELECT COUNT(*) FROM subjective").fetchone()[0] == 1
    assert conn.execute("SELECT sleep_feel FROM subjective").fetchone()[0] == 4
    conn.close()


def test_log_subjective_validates_range(data_env):
    out = mcp_server.log_subjective(6, 2, 2, 4)
    assert out["error"] == "invalid_value"


def test_log_strength_session_supersedes_garmin(data_env):
    conn = db.connect(data_env.db_path)
    aid = _seed_strength(conn, weeks=1)
    conn.commit()
    conn.close()
    d = (TODAY - timedelta(days=1)).isoformat()
    out = mcp_server.log_strength_session(
        d,
        [{"exercise": "BENCH_PRESS", "sets": [{"reps": 5, "weight_kg": 85, "rir": 1}] * 3}],
    )
    assert out["activity_id"] == aid
    assert out["sets_written"] == 3
    assert out["superseded_garmin_sets"] == 3
    conn = db.connect(data_env.db_path, read_only=True)
    live = conn.execute(
        "SELECT source, COUNT(*) c FROM strength_sets WHERE superseded = 0 GROUP BY source"
    ).fetchall()
    assert {r["source"]: r["c"] for r in live} == {"manual": 3}
    # garmin-radene finnes fortsatt (audit), bare superseded
    total = conn.execute("SELECT COUNT(*) FROM strength_sets").fetchone()[0]
    assert total == 6
    conn.close()


def test_log_strength_session_pure_manual_without_activity(data_env):
    db.connect(data_env.db_path).close()  # opprett tom db
    out = mcp_server.log_strength_session(
        TODAY.isoformat(),
        [{"exercise": "goblet squat", "sets": [{"reps": 10, "weight_kg": 24}]}],
    )
    assert out["activity_id"] is None
    assert "manuelle" in out["conclusion"]
    conn = db.connect(data_env.db_path, read_only=True)
    row = conn.execute("SELECT exercise, muscle_group FROM strength_sets").fetchone()
    assert row["exercise"] == "GOBLET_SQUAT"
    assert row["muscle_group"] == "legs"
    conn.close()


def test_push_workout_success(data_env, fake_client, monkeypatch):
    from garmin_pt.garmin import auth

    monkeypatch.setattr(auth, "login", lambda settings, interactive=False: fake_client)
    db.connect(data_env.db_path).close()
    spec = {
        "name": "Uke 36 HIIT",
        "sport": "hiit",
        "steps": [
            {"kind": "interval", "work_s": 240, "rest_s": 180, "repeats": 4, "target": "hr_zone_5"}
        ],
    }
    schedule = (TODAY + timedelta(days=2)).isoformat()
    out = mcp_server.push_workout_to_garmin(spec, schedule_date=schedule)
    assert out["garmin_workout_id"] == 4242
    assert out["scheduled_for"] == schedule
    assert fake_client.uploaded_workouts[0]["workoutName"] == "Uke 36 HIIT"
    assert fake_client.scheduled == [(4242, schedule)]
    conn = db.connect(data_env.db_path, read_only=True)
    plan = conn.execute("SELECT * FROM plan").fetchone()
    assert plan["garmin_workout_id"] == "4242"
    assert plan["date"] == schedule
    conn.close()


def test_push_workout_auth_expired(data_env, monkeypatch):
    from garmin_pt.garmin import auth
    from garmin_pt.garmin.client import AuthError

    def boom(settings, interactive=False):
        raise AuthError("utløpt")

    monkeypatch.setattr(auth, "login", boom)
    out = mcp_server.push_workout_to_garmin(
        {
            "name": "x",
            "sport": "running",
            "steps": [{"kind": "steady", "duration_min": 30, "target": "hr_zone_2"}],
        }
    )
    assert out["error"] == "auth_expired"
    assert "garmin-pt auth" in out["action"]


def test_push_workout_invalid_spec_short_circuits(data_env):
    out = mcp_server.push_workout_to_garmin({"name": "x"})
    assert out["error"] == "invalid_spec"
