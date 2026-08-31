from datetime import date

from conftest import FakeGarminClient

from garmin_pt.garmin.client import AuthError, GarminClient, GarminClientProtocol, RateLimited
from garmin_pt.ingest import runner as r

FROM, TO = date(2026, 8, 27), date(2026, 8, 30)


def _run(fake, conn, settings, **kw):
    sleeps: list[float] = []
    ing = r.IngestRunner(fake, conn, settings, sleeper=sleeps.append, **kw)
    result = ing.run(FROM, TO)
    return result, sleeps


def test_protocol_conformance():
    proto_methods = {n for n in dir(GarminClientProtocol) if not n.startswith("_")}
    for impl in (GarminClient, FakeGarminClient):
        missing = proto_methods - set(dir(impl))
        assert not missing, f"{impl.__name__} mangler {missing}"


def test_happy_path_and_idempotency(fake_client, db_conn, settings):
    result, sleeps = _run(fake_client, db_conn, settings)
    assert result.status == "ok"
    assert result.days_done == 4
    assert result.api_calls == len(sleeps)  # kun throttle-søvn, ingen backoff

    assert db_conn.execute("SELECT COUNT(*) FROM daily").fetchone()[0] == 4
    assert db_conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 2
    assert db_conn.execute("SELECT COUNT(*) FROM strength_sets").fetchone()[0] == 3
    assert r.get_watermark(db_conn, "daily") == "2026-08-30"
    assert r.get_watermark(db_conn, "activities") == "2026-08-30"
    metrics = db_conn.execute("SELECT * FROM metrics").fetchall()
    assert len(metrics) == 1
    assert metrics[0]["week_start"] == "2026-08-24"
    assert metrics[0]["vo2max"] == 52.3
    assert metrics[0]["weekly_trimp"] is not None

    # kjøring nummer to: identiske radtall (alle skriv er upserts)
    result2, _ = _run(FakeGarminClient(), db_conn, settings)
    assert result2.status == "ok"
    assert db_conn.execute("SELECT COUNT(*) FROM daily").fetchone()[0] == 4
    assert db_conn.execute("SELECT COUNT(*) FROM strength_sets").fetchone()[0] == 3


def test_429_exhausted_aborts_with_watermark_intact(fake_client, db_conn, settings):
    fake_client.fail_queue["hrv_day"] = [RateLimited("429")] * 10
    result, sleeps = _run(fake_client, db_conn, settings)
    assert result.status == "rate_limited"
    assert result.days_done == 0
    assert r.get_watermark(db_conn, "daily") is None
    # backoff-søvn utover throttle: 2, 4, 8, 16, 32, 64
    assert [s for s in sleeps if s != settings.load.throttle_seconds] == [2, 4, 8, 16, 32, 64]
    run_row = db_conn.execute("SELECT status FROM sync_runs").fetchone()
    assert run_row["status"] == "rate_limited"


def test_429_once_recovers(fake_client, db_conn, settings):
    fake_client.fail_queue["sleep_day"] = [RateLimited("429")]
    result, sleeps = _run(fake_client, db_conn, settings)
    assert result.status == "ok"
    assert 2 in sleeps  # én backoff


def test_partial_run_resumes_from_watermark(fake_client, db_conn, settings):
    # dag 1 og 2 fine; tredje dags rhr-kall får varig 429
    fake_client.fail_queue["rhr_day"] = [None, None] + [RateLimited("429")] * 10
    result, _ = _run(fake_client, db_conn, settings)
    assert result.status == "rate_limited"
    assert result.days_done == 2
    assert r.get_watermark(db_conn, "daily") == "2026-08-28"
    # neste kjøring starter dagen etter watermark
    assert r.default_range(db_conn, TO) == (date(2026, 8, 29), TO)


def test_auth_error_aborts_loudly(fake_client, db_conn, settings):
    fake_client.fail_queue["hrv_day"] = [AuthError("token utløpt")]
    result, _ = _run(fake_client, db_conn, settings)
    assert result.status == "auth_error"
    assert "garmin-pt auth" in (result.error or "")


def test_raw_payloads_stored_and_optional(fake_client, db_conn, settings):
    _run(fake_client, db_conn, settings)
    n = db_conn.execute("SELECT COUNT(*) FROM raw_payloads").fetchone()[0]
    assert n > 0
    domains = {row[0] for row in db_conn.execute("SELECT DISTINCT domain FROM raw_payloads")}
    assert domains == {"daily", "activities", "strength", "metrics"}

    conn2 = __import__("garmin_pt.db", fromlist=["db"]).connect(settings.data_dir / "no_raw.db")
    ing = r.IngestRunner(
        FakeGarminClient(), conn2, settings, sleeper=lambda s: None, store_raw=False
    )
    ing.run(FROM, TO)
    assert conn2.execute("SELECT COUNT(*) FROM raw_payloads").fetchone()[0] == 0


def test_default_range_without_watermark(db_conn):
    assert r.default_range(db_conn, date(2026, 8, 31)) == (
        date(2026, 8, 24),
        date(2026, 8, 31),
    )
