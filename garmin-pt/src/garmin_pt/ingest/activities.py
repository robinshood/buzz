"""Ren transform: ett element fra get_activities() → activities-rad.

TRIMP beregnes her ved ingest (Edwards fra tid-i-sone, med fallback til
Garmins egen load og deretter varighet) og lagres på raden.
"""

from __future__ import annotations

from ..analytics.load import activity_trimp

STRENGTH_TYPES = {"strength_training", "indoor_strength"}


def is_strength(activity_type: str | None) -> bool:
    return activity_type in STRENGTH_TYPES


def activity_row(raw: dict) -> dict | None:
    activity_id = raw.get("activityId")
    type_key = (raw.get("activityType") or {}).get("typeKey")
    start = raw.get("startTimeLocal")
    if activity_id is None or type_key is None or not start:
        return None

    zones = [raw.get(f"hrTimeInZone_{i}") for i in range(1, 6)]
    trimp, _basis = activity_trimp(zones, raw.get("activityTrainingLoad"), raw.get("duration"))

    def _int(v):
        return int(v) if isinstance(v, int | float) else None

    return {
        "activity_id": activity_id,
        "date": start[:10],
        "start_time": start,
        "activity_type": type_key,
        "name": raw.get("activityName"),
        "duration_s": raw.get("duration"),
        "distance_m": raw.get("distance"),
        "avg_hr": _int(raw.get("averageHR")),
        "max_hr": _int(raw.get("maxHR")),
        "hr_zone_1_s": zones[0],
        "hr_zone_2_s": zones[1],
        "hr_zone_3_s": zones[2],
        "hr_zone_4_s": zones[3],
        "hr_zone_5_s": zones[4],
        "aerobic_te": raw.get("aerobicTrainingEffect"),
        "anaerobic_te": raw.get("anaerobicTrainingEffect"),
        "calories": raw.get("calories"),
        "garmin_load": raw.get("activityTrainingLoad"),
        "trimp": trimp,
    }
