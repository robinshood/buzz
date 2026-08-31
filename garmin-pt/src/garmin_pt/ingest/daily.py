"""Ren transform: rå Garmin-payloads for én dag → daily-rad.

Feltstiene er provisoriske til første live-kjøring; `garmin-pt reparse`
re-kjører transformen fra raw_payloads etter en eventuell parser-fiks.
"""

from __future__ import annotations

from typing import Any


def _dig(d: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d


def _min(seconds: Any) -> float | None:
    return round(seconds / 60.0, 1) if isinstance(seconds, int | float) else None


def daily_row(
    date: str,
    hrv: dict | None,
    sleep: dict | None,
    rhr: dict | None,
    summary: dict | None,
    weigh_ins: dict | None,
) -> dict:
    row: dict = {"date": date}

    row["hrv_last_night_avg"] = _dig(hrv, "hrvSummary", "lastNightAvg")
    row["hrv_status"] = _dig(hrv, "hrvSummary", "status")

    dto = _dig(sleep, "dailySleepDTO") or {}
    row["sleep_score"] = _dig(dto, "sleepScores", "overall", "value")
    row["sleep_duration_min"] = _min(dto.get("sleepTimeSeconds"))
    row["sleep_deep_min"] = _min(dto.get("deepSleepSeconds"))
    row["sleep_rem_min"] = _min(dto.get("remSleepSeconds"))
    row["sleep_light_min"] = _min(dto.get("lightSleepSeconds"))
    row["sleep_awake_min"] = _min(dto.get("awakeSleepSeconds"))

    rhr_entries = _dig(rhr, "allMetrics", "metricsMap", "WELLNESS_RESTING_HEART_RATE")
    rhr_value = None
    if isinstance(rhr_entries, list) and rhr_entries:
        rhr_value = rhr_entries[0].get("value")
    if rhr_value is None:
        rhr_value = _dig(summary, "restingHeartRate") or _dig(sleep, "restingHeartRate")
    row["resting_hr"] = int(rhr_value) if rhr_value is not None else None

    row["body_battery_high"] = _dig(summary, "bodyBatteryHighestValue")
    row["body_battery_low"] = _dig(summary, "bodyBatteryLowestValue")
    row["stress_avg"] = _dig(summary, "averageStressLevel")
    row["steps"] = _dig(summary, "totalSteps")

    weights = _dig(weigh_ins, "dateWeightList")
    if isinstance(weights, list) and weights:
        grams = weights[-1].get("weight")
        row["weight_kg"] = round(grams / 1000.0, 1) if grams else None
    else:
        row["weight_kg"] = None

    return row
