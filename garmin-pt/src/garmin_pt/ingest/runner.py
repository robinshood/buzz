"""Ingest-orkestrering: dag-for-dag henting med throttle, 429-backoff,
watermarks og sync_runs-bokføring.

Resumbarhet: alle skriv er upserts, og watermark flyttes bare etter en HELT
ferdig dag — en avbrutt backfill fortsetter der den slapp på neste kjøring.
429 etter uttømt backoff avslutter kjøringen med status 'rate_limited' og
exit uten feil; neste cron-kjøring tar resten.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date as Date
from datetime import timedelta

from .. import db
from ..config import Settings
from ..garmin.client import (
    AuthError,
    GarminClientProtocol,
    GarminUnavailable,
    RateLimited,
)
from . import activities as t_act
from . import daily as t_daily
from . import metrics as t_metrics
from . import strength as t_strength

BACKOFF_DELAYS = [2, 4, 8, 16, 32, 64]
BACKOFF_CAP = 120.0


@dataclass
class RunResult:
    status: str  # ok | partial | rate_limited | auth_error | error
    days_done: int = 0
    api_calls: int = 0
    error: str | None = None


class _Aborted(Exception):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


def get_watermark(conn: sqlite3.Connection, domain: str) -> str | None:
    row = conn.execute(
        "SELECT last_synced_date FROM sync_watermarks WHERE domain = ?", (domain,)
    ).fetchone()
    return row[0] if row else None


def set_watermark(conn: sqlite3.Connection, domain: str, date_str: str) -> None:
    db.upsert(
        conn,
        "sync_watermarks",
        {"domain": domain, "last_synced_date": date_str},
        ["domain"],
        touch="updated_at",
    )


class IngestRunner:
    def __init__(
        self,
        client: GarminClientProtocol,
        conn: sqlite3.Connection,
        settings: Settings,
        *,
        sleeper: Callable[[float], None] = time.sleep,
        store_raw: bool = True,
    ) -> None:
        self.client = client
        self.conn = conn
        self.settings = settings
        self.sleeper = sleeper
        self.store_raw = store_raw
        self.api_calls = 0
        self.days_done = 0

    # -- kall-innpakning ---------------------------------------------------

    def _call(self, fn, *args):
        """Throttle + eksponentiell backoff rundt hvert Garmin-kall."""
        self.sleeper(self.settings.load.throttle_seconds)
        attempt = 0
        while True:
            try:
                self.api_calls += 1
                return fn(*args)
            except RateLimited as e:
                if attempt >= len(BACKOFF_DELAYS):
                    raise _Aborted("rate_limited", str(e)) from e
                self.sleeper(min(BACKOFF_DELAYS[attempt], BACKOFF_CAP))
                attempt += 1
            except AuthError as e:
                raise _Aborted("auth_error", f"{e} — kjør 'garmin-pt auth' lokalt") from e
            except GarminUnavailable as e:
                if attempt >= 2:
                    raise _Aborted("error", str(e)) from e
                self.sleeper(BACKOFF_DELAYS[attempt])
                attempt += 1

    def _store_raw(self, domain: str, date_str: str, endpoint: str, payload) -> None:
        if not self.store_raw or payload is None:
            return
        db.upsert(
            self.conn,
            "raw_payloads",
            {
                "domain": domain,
                "date": date_str,
                "endpoint": endpoint,
                "payload": json.dumps(payload, ensure_ascii=False),
            },
            ["domain", "date", "endpoint"],
        )

    # -- domener -----------------------------------------------------------

    def _ingest_day(self, day: Date) -> None:
        d = day.isoformat()
        payloads = {}
        for endpoint, fn in (
            ("hrv_day", self.client.hrv_day),
            ("sleep_day", self.client.sleep_day),
            ("rhr_day", self.client.rhr_day),
            ("user_summary", self.client.user_summary),
            ("weigh_ins", self.client.weigh_ins),
        ):
            payloads[endpoint] = self._call(fn, d)
            self._store_raw("daily", d, endpoint, payloads[endpoint])
        row = t_daily.daily_row(
            d,
            hrv=payloads["hrv_day"],
            sleep=payloads["sleep_day"],
            rhr=payloads["rhr_day"],
            summary=payloads["user_summary"],
            weigh_ins=payloads["weigh_ins"],
        )
        db.upsert(self.conn, "daily", row, ["date"], touch="updated_at")
        self.conn.commit()

    def _ingest_activities(self, date_from: Date, date_to: Date) -> None:
        start, page_size = 0, 50
        while True:
            page = self._call(self.client.activities, start, page_size)
            if not page:
                break
            done = False
            for raw in page:
                row = t_act.activity_row(raw)
                if row is None:
                    continue
                day = Date.fromisoformat(row["date"])
                if day > date_to:
                    continue
                if day < date_from:
                    done = True
                    break
                self._store_raw("activities", row["date"], f"activity:{row['activity_id']}", raw)
                db.upsert(self.conn, "activities", row, ["activity_id"], touch="updated_at")
                if t_act.is_strength(row["activity_type"]):
                    self._ingest_strength(row["activity_id"], row["date"])
                self.conn.commit()
            if done or len(page) < page_size:
                break
            start += page_size
        set_watermark(self.conn, "activities", date_to.isoformat())
        self.conn.commit()

    def _ingest_strength(self, activity_id: int, date_str: str) -> None:
        raw = self._call(self.client.exercise_sets, activity_id)
        if raw is None:
            return
        self._store_raw("strength", date_str, f"exercise_sets:{activity_id}", raw)
        for row in t_strength.strength_rows(
            activity_id,
            date_str,
            raw,
            epley_max_reps=self.settings.e1rm.epley_max_reps,
        ):
            db.upsert(
                self.conn,
                "strength_sets",
                row,
                ["activity_id", "set_index"],
                conflict_where="source = 'garmin'",
                touch="updated_at",
            )

    def _ingest_metrics(self, asof: Date) -> None:
        d = asof.isoformat()
        status = self._call(self.client.training_status, d)
        self._store_raw("metrics", d, "training_status", status)
        max_metrics = self._call(self.client.max_metrics, d)
        self._store_raw("metrics", d, "max_metrics", max_metrics)
        week_start = t_metrics.week_start_of(asof)
        row = t_metrics.metrics_row(week_start, status, max_metrics)
        row.update(t_metrics.weekly_aggregates(self.conn, week_start))
        db.upsert(self.conn, "metrics", row, ["week_start"], touch="updated_at")
        set_watermark(self.conn, "metrics", d)
        self.conn.commit()

    # -- kjøring -----------------------------------------------------------

    def run(self, date_from: Date, date_to: Date, mode: str = "daily") -> RunResult:
        run_id = self.conn.execute(
            "INSERT INTO sync_runs (mode, date_from, date_to) VALUES (?, ?, ?)",
            (mode, date_from.isoformat(), date_to.isoformat()),
        ).lastrowid
        self.conn.commit()

        status, error = "ok", None
        try:
            day = date_from
            while day <= date_to:
                self._ingest_day(day)
                set_watermark(self.conn, "daily", day.isoformat())
                self.conn.commit()
                self.days_done += 1
                day += timedelta(days=1)
            self._ingest_activities(date_from, date_to)
            self._ingest_metrics(date_to)
        except _Aborted as a:
            status, error = a.status, str(a)
        except Exception as e:  # noqa: BLE001 — bokfør alt, mist aldri en kjøring
            status, error = "error", f"{type(e).__name__}: {e}"

        self.conn.execute(
            "UPDATE sync_runs SET finished_at = datetime('now'), status = ?, "
            "days_done = ?, api_calls = ?, error = ? WHERE id = ?",
            (status, self.days_done, self.api_calls, error, run_id),
        )
        self.conn.commit()
        return RunResult(status, self.days_done, self.api_calls, error)


def default_range(conn: sqlite3.Connection, today: Date) -> tuple[Date, Date]:
    """Fra dagen etter daily-watermark (maks 7 dager tilbake uten watermark)
    til og med i dag."""
    wm = get_watermark(conn, "daily")
    if wm is None:
        return today - timedelta(days=7), today
    start = Date.fromisoformat(wm) + timedelta(days=1)
    return min(start, today), today
