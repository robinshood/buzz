"""Ren transform: get_activity_exercise_sets() → strength_sets-rader.

Klokka gjetter øvelse og reps og mangler ofte vekt — alt er nullable, og
e1RM settes bare når vekt+reps finnes (og reps er under Epley-taket).
"""

from __future__ import annotations

from ..analytics.strengthprog import epley

# Substring-oppslag mot Garmins category. REKKEFØLGEN BETYR NOE:
# LEG_CURL må treffe 'legs' før CURL treffer 'biceps'.
_MUSCLE_BY_CATEGORY: dict[str, str] = {
    "BENCH_PRESS": "chest",
    "CHEST": "chest",
    "FLYE": "chest",
    "PUSH_UP": "chest",
    "DIP": "chest",
    "SQUAT": "legs",
    "LUNGE": "legs",
    "LEG_PRESS": "legs",
    "LEG_EXTENSION": "legs",
    "LEG_CURL": "legs",
    "CALF": "legs",
    "DEADLIFT": "legs",
    "HIP": "legs",
    "ROW": "back",
    "PULL_UP": "back",
    "PULLUP": "back",
    "LAT_PULL": "back",
    "PULLDOWN": "back",
    "SHOULDER_PRESS": "shoulders",
    "LATERAL_RAISE": "shoulders",
    "SHRUG": "shoulders",
    "TRICEP": "triceps",
    "CURL": "biceps",
    "PLANK": "core",
    "CRUNCH": "core",
    "SIT_UP": "core",
    "CORE": "core",
    "CARRY": "core",
    "FARMER": "core",
}


def muscle_group_for(category: str | None) -> str | None:
    if not category:
        return None
    upper = category.upper()
    for key, group in _MUSCLE_BY_CATEGORY.items():
        if key in upper:
            return group
    return None


def normalize_exercise(exercises: list | None) -> tuple[str, str | None]:
    """(øvelsesnavn, muskelgruppe) fra klokkas gjetteliste — mest sannsynlige
    vinner; ukjent kategori beholder rånavnet med muscle_group=None."""
    if not exercises:
        return "UNKNOWN", None
    best = max(exercises, key=lambda e: e.get("probability") or 0)
    category = best.get("category")
    name = best.get("name") or category or "UNKNOWN"
    return name, muscle_group_for(category)


def _weight_kg(raw_weight: float | None) -> float | None:
    """Garmin oppgir vekt i gram. Verdier < 400 tolkes som allerede-kg
    (ingen løfter 400+ kg; ingen loggfører 0,4 kg i gram) — provisorisk
    enhetsvern til første live-data er verifisert."""
    if raw_weight is None or raw_weight <= 0:
        return None
    if raw_weight < 400:
        return round(float(raw_weight), 1)
    return round(raw_weight / 1000.0, 1)


def strength_rows(
    activity_id: int, date: str, raw: dict, *, epley_max_reps: int = 12
) -> list[dict]:
    rows: list[dict] = []
    set_index = 0
    for s in raw.get("exerciseSets") or []:
        if s.get("setType") != "ACTIVE":
            continue
        set_index += 1
        exercise, muscle = normalize_exercise(s.get("exercises"))
        reps = s.get("repetitionCount")
        weight = _weight_kg(s.get("weight"))
        rows.append(
            {
                "activity_id": activity_id,
                "date": date,
                "exercise": exercise,
                "muscle_group": muscle,
                "set_index": set_index,
                "reps": int(reps) if reps else None,
                "weight_kg": weight,
                "duration_s": s.get("duration"),
                "e1rm": epley(weight, int(reps) if reps else None, epley_max_reps),
                "source": "garmin",
            }
        )
    return rows
