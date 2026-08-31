import json

import pytest
from conftest import load_fixture

from garmin_pt import cli, db


@pytest.fixture
def data_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GARMIN_PT_DATA_DIR", str(tmp_path / "data"))
    from garmin_pt.config import load_settings

    return load_settings()


def test_parser_accepts_documented_commands():
    p = cli.build_parser()
    args = p.parse_args(["ingest", "--backfill", "365", "--no-raw"])
    assert args.backfill == 365 and args.no_raw
    args = p.parse_args(["ingest", "--from", "2026-01-01", "--to", "2026-02-01"])
    assert args.date_from == "2026-01-01"
    args = p.parse_args(
        ["subjective", "--sleep-feel", "3", "--stress", "2", "--soreness", "2", "--motivation", "4"]
    )
    assert args.sleep_feel == 3


def test_status_without_db(data_env, capsys):
    assert cli.main(["status"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "aldri synket" in out["db"]
    assert out["tokens"]["present"] is False


def test_status_flags_failed_runs(data_env, capsys):
    conn = db.connect(data_env.db_path)
    conn.execute(
        "INSERT INTO sync_runs (mode, status, error) VALUES ('daily', 'auth_error', 'token utløpt')"
    )
    conn.commit()
    conn.close()
    assert cli.main(["status"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "SISTE KJØRINGER FEILET" in out.get("attention", "")


def test_subjective_via_flags(data_env, capsys):
    rc = cli.main(
        [
            "subjective",
            "--sleep-feel",
            "3",
            "--stress",
            "2",
            "--soreness",
            "2",
            "--motivation",
            "4",
            "--note",
            "fin dag",
        ]
    )
    assert rc == 0
    conn = db.connect(data_env.db_path, read_only=True)
    assert conn.execute("SELECT COUNT(*) FROM subjective").fetchone()[0] == 1
    conn.close()


def _seed_raw(conn):
    payloads = [
        ("daily", "2026-08-30", "hrv_day", load_fixture("hrv_day.json")),
        ("daily", "2026-08-30", "sleep_day", load_fixture("sleep_day.json")),
        ("daily", "2026-08-30", "rhr_day", load_fixture("rhr_day.json")),
        ("daily", "2026-08-30", "user_summary", load_fixture("user_summary.json")),
        ("daily", "2026-08-30", "weigh_ins", load_fixture("weigh_ins.json")),
        (
            "activities",
            "2026-08-28",
            "activity:987654322",
            load_fixture("activities_page.json")[1],
        ),
        (
            "strength",
            "2026-08-28",
            "exercise_sets:987654322",
            load_fixture("exercise_sets_full.json"),
        ),
    ]
    for domain, d, endpoint, payload in payloads:
        conn.execute(
            "INSERT INTO raw_payloads (domain, date, endpoint, payload) VALUES (?, ?, ?, ?)",
            (domain, d, endpoint, json.dumps(payload)),
        )
    conn.commit()


def test_reparse_rebuilds_rows_from_raw(data_env, capsys):
    conn = db.connect(data_env.db_path)
    _seed_raw(conn)
    conn.close()
    assert cli.main(["reparse"]) == 0
    counts = json.loads(capsys.readouterr().out)
    assert counts == {"daily": 1, "activities": 1, "strength": 3, "dumped": 0}
    conn = db.connect(data_env.db_path, read_only=True)
    assert conn.execute("SELECT hrv_last_night_avg FROM daily").fetchone()[0] == 48
    assert conn.execute("SELECT COUNT(*) FROM strength_sets").fetchone()[0] == 3
    conn.close()


def test_reparse_dump_fixtures(data_env, tmp_path, capsys):
    conn = db.connect(data_env.db_path)
    _seed_raw(conn)
    conn.close()
    outdir = tmp_path / "dump"
    assert cli.main(["reparse", "--dump-fixtures", str(outdir)]) == 0
    counts = json.loads(capsys.readouterr().out)
    assert counts["dumped"] == 7
    assert (outdir / "daily_hrv_day_2026-08-30.json").exists()
    assert (outdir / "strength_exercise_sets_987654322_2026-08-28.json").exists()
