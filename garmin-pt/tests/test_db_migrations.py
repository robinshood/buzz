import sqlite3

from garmin_pt import db
from garmin_pt.schema import MIGRATIONS

EXPECTED_TABLES = {
    "daily",
    "activities",
    "strength_sets",
    "metrics",
    "plan",
    "subjective",
    "sync_watermarks",
    "sync_runs",
    "raw_payloads",
}


def _tables(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {r["name"] for r in rows}


def test_fresh_db_reaches_latest_version(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == len(MIGRATIONS)
    assert _tables(conn) == EXPECTED_TABLES


def test_reopen_is_noop(tmp_path):
    path = tmp_path / "t.db"
    db.connect(path).close()
    conn = db.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    assert _tables(conn) == EXPECTED_TABLES


def test_read_only_connection_cannot_write(tmp_path):
    path = tmp_path / "t.db"
    db.connect(path).close()
    ro = db.connect(path, read_only=True)
    try:
        ro.execute("INSERT INTO subjective (date, sleep_feel) VALUES ('2026-01-01', 3)")
        raised = False
    except sqlite3.OperationalError:
        raised = True
    assert raised


def test_upsert_is_idempotent(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    row = {"date": "2026-08-01", "resting_hr": 47, "sleep_score": 80}
    db.upsert(conn, "daily", row, ["date"], touch="updated_at")
    db.upsert(conn, "daily", {**row, "resting_hr": 48}, ["date"], touch="updated_at")
    got = conn.execute("SELECT COUNT(*) c, MAX(resting_hr) hr FROM daily").fetchone()
    assert got["c"] == 1
    assert got["hr"] == 48


def test_upsert_partial_index_conflict(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO activities (activity_id, date, activity_type) "
        "VALUES (11, '2026-08-01', 'strength_training')"
    )
    base = {
        "activity_id": 11,
        "date": "2026-08-01",
        "exercise": "BENCH_PRESS",
        "set_index": 1,
        "reps": 5,
        "weight_kg": 80.0,
        "source": "garmin",
    }
    for _ in range(2):
        db.upsert(
            conn,
            "strength_sets",
            base,
            ["activity_id", "set_index"],
            conflict_where="source = 'garmin'",
            touch="updated_at",
        )
    # manuell rad med samme (activity_id, set_index) skal IKKE kollidere
    conn.execute(
        "INSERT INTO strength_sets (activity_id, date, exercise, set_index, reps, "
        "weight_kg, source) VALUES (11, '2026-08-01', 'BENCH_PRESS', 1, 5, 82.5, 'manual')"
    )
    rows = conn.execute("SELECT source, COUNT(*) c FROM strength_sets GROUP BY source").fetchall()
    assert {r["source"]: r["c"] for r in rows} == {"garmin": 1, "manual": 1}
