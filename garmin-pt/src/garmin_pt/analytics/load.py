"""Belastning: Edwards TRIMP, ACWR (7d:28d), Foster-monotoni, ukesaggregat."""

from __future__ import annotations

import sqlite3
import statistics
from collections.abc import Mapping, Sequence
from datetime import date as Date
from datetime import timedelta


def edwards_trimp(zone_seconds: Sequence[float | None]) -> float | None:
    """Σ(sone-nr × minutter i sonen) for soner 1–5. None uten sonedata."""
    if not zone_seconds or all(z is None for z in zone_seconds):
        return None
    return round(sum((i + 1) * (z or 0.0) / 60.0 for i, z in enumerate(zone_seconds)), 1)


def activity_trimp(
    zone_seconds: Sequence[float | None],
    garmin_load: float | None,
    duration_s: float | None,
) -> tuple[float | None, str]:
    """TRIMP for én økt med fallback-kjede. Returnerer (verdi, basis) der basis er
    'edwards' | 'garmin_load' | 'duration_floor' | 'none' — styrkeøkter uten HR
    får varighet i minutter som gulv i stedet for 0."""
    trimp = edwards_trimp(zone_seconds)
    if trimp is not None and trimp > 0:
        return trimp, "edwards"
    if garmin_load:
        return round(float(garmin_load), 1), "garmin_load"
    if duration_s:
        return round(duration_s / 60.0, 1), "duration_floor"
    return None, "none"


def acwr(daily_trimp: Mapping[Date, float], asof: Date) -> float | None:
    """Akutt:kronisk = sum(7d) / (sum(28d)/4). None ved < 14 dagers historikk
    eller null kronisk last (kalibrerer)."""
    if not daily_trimp:
        return None
    if (asof - min(daily_trimp)).days < 13:
        return None
    acute = sum(v for d, v in daily_trimp.items() if 0 <= (asof - d).days < 7)
    chronic = sum(v for d, v in daily_trimp.items() if 0 <= (asof - d).days < 28) / 4.0
    if chronic <= 0:
        return None
    return round(acute / chronic, 2)


def monotony(daily_trimp_7d: Sequence[float]) -> float | None:
    """Foster-monotoni: mean/stdev over 7 kalenderdager (hviledager = 0.0).
    None ved uniform uke (stdev 0) eller tom uke — kalles ut som flagg av
    verktøylaget i stedet for å returnere uendelig."""
    if len(daily_trimp_7d) < 7:
        return None
    mean = statistics.mean(daily_trimp_7d)
    sd = statistics.stdev(daily_trimp_7d)
    if sd == 0 or mean == 0:
        return None
    return round(mean / sd, 2)


def daily_trimp_map(conn: sqlite3.Connection, asof: Date, days: int = 35) -> dict[Date, float]:
    rows = conn.execute(
        "SELECT date, SUM(COALESCE(trimp, 0)) AS t FROM activities "
        "WHERE date > date(?, ?) AND date <= ? GROUP BY date",
        (asof.isoformat(), f"-{days} days", asof.isoformat()),
    ).fetchall()
    return {Date.fromisoformat(r["date"]): r["t"] or 0.0 for r in rows}


def monotony_7d(conn: sqlite3.Connection, asof: Date) -> float | None:
    per_day = daily_trimp_map(conn, asof, days=7)
    series = [per_day.get(asof - timedelta(days=i), 0.0) for i in range(6, -1, -1)]
    return monotony(series)


def weekly_load(conn: sqlite3.Connection, weeks: int, asof: Date) -> list[dict]:
    """Ukesrader (nyest først): økter, minutter, TRIMP, minutter per HR-sone.
    Uke = man–søn; week_start er mandagen."""
    rows = conn.execute(
        """
        SELECT date(date, 'weekday 0', '-6 days') AS week_start,
               COUNT(*)                            AS sessions,
               ROUND(SUM(COALESCE(duration_s, 0)) / 60.0, 0)  AS minutes,
               ROUND(SUM(COALESCE(trimp, 0)), 0)   AS trimp,
               ROUND(SUM(COALESCE(hr_zone_1_s, 0)) / 60.0, 0) AS z1,
               ROUND(SUM(COALESCE(hr_zone_2_s, 0)) / 60.0, 0) AS z2,
               ROUND(SUM(COALESCE(hr_zone_3_s, 0)) / 60.0, 0) AS z3,
               ROUND(SUM(COALESCE(hr_zone_4_s, 0)) / 60.0, 0) AS z4,
               ROUND(SUM(COALESCE(hr_zone_5_s, 0)) / 60.0, 0) AS z5
        FROM activities
        WHERE date > date(?, ?) AND date <= ?
        GROUP BY week_start
        ORDER BY week_start DESC
        """,
        (asof.isoformat(), f"-{weeks * 7} days", asof.isoformat()),
    ).fetchall()
    return [
        {
            "week_start": r["week_start"],
            "sessions": r["sessions"],
            "minutes": r["minutes"],
            "trimp": r["trimp"],
            "zone_minutes": [r["z1"], r["z2"], r["z3"], r["z4"], r["z5"]],
        }
        for r in rows
    ]
