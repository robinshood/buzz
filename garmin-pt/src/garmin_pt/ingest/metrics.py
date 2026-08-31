"""Ukentlig metrics-rad: Garmin-felter fra API + aggregat fra egen database."""

from __future__ import annotations

import sqlite3
from datetime import date as Date
from datetime import timedelta
from typing import Any

from ..analytics.load import acwr, daily_trimp_map, monotony_7d


def week_start_of(day: Date) -> Date:
    return day - timedelta(days=day.weekday())


def _dig(d: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d


def metrics_row(
    week_start: Date, training_status: dict | None, max_metrics: dict | list | None
) -> dict:
    row: dict = {"week_start": week_start.isoformat()}

    vo2 = None
    mm = max_metrics[0] if isinstance(max_metrics, list) and max_metrics else max_metrics
    vo2 = _dig(mm, "generic", "vo2MaxPreciseValue") or _dig(mm, "generic", "vo2MaxValue")
    if vo2 is None:
        vo2 = _dig(training_status, "mostRecentVO2Max", "generic", "vo2MaxPreciseValue")
    row["vo2max"] = vo2

    status_phrase = None
    threshold = None
    per_device = _dig(training_status, "mostRecentTrainingStatus", "latestTrainingStatusData") or {}
    if isinstance(per_device, dict) and per_device:
        device_data = next(iter(per_device.values()))
        phrase = device_data.get("trainingStatusFeedbackPhrase")
        if isinstance(phrase, str) and phrase:
            # "PRODUCTIVE_4" → "PRODUCTIVE"
            status_phrase = phrase.rsplit("_", 1)[0] if phrase[-1].isdigit() else phrase
        threshold = device_data.get("lactateThresholdHeartRate")
    row["training_status"] = status_phrase
    row["threshold_hr"] = int(threshold) if threshold else None
    return row


def weekly_aggregates(conn: sqlite3.Connection, week_start: Date) -> dict:
    """Beregnes fra egne tabeller — aldri fra Garmin: ukens TRIMP, snitt
    hvilepuls/vekt, ACWR og monotoni per uke-slutt."""
    week_end = week_start + timedelta(days=6)
    trimp = conn.execute(
        "SELECT SUM(COALESCE(trimp, 0)) FROM activities WHERE date >= ? AND date <= ?",
        (week_start.isoformat(), week_end.isoformat()),
    ).fetchone()[0]
    avgs = conn.execute(
        "SELECT AVG(resting_hr) rhr, AVG(weight_kg) w FROM daily WHERE date >= ? AND date <= ?",
        (week_start.isoformat(), week_end.isoformat()),
    ).fetchone()
    return {
        "weekly_trimp": round(trimp, 1) if trimp else None,
        "resting_hr_avg": round(avgs["rhr"], 1) if avgs["rhr"] is not None else None,
        "weight_avg_kg": round(avgs["w"], 1) if avgs["w"] is not None else None,
        "acwr": acwr(daily_trimp_map(conn, week_end, days=35), week_end),
        "monotony": monotony_7d(conn, week_end),
    }
