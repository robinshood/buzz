"""Vår økt-spec → Garmin Connect workout-JSON (for upload_workout).

Spec-format (det PT-en produserer):
    {
      "name": "Uke 36 HIIT",
      "sport": "running" | "strength" | "hiit",
      "steps": [
        {"kind": "warmup",   "duration_min": 10, "target": "hr_zone_1"},
        {"kind": "steady",   "duration_min": 40, "target": "hr_zone_2"},
        {"kind": "interval", "work_s": 240, "rest_s": 180, "repeats": 4,
         "target": "hr_zone_5"},
        {"kind": "exercise", "exercise": "BENCH_PRESS", "sets": 4, "reps": 6,
         "weight_kg": 80, "rest_s": 150},
        {"kind": "cooldown", "duration_min": 5}
      ]
    }

MERK: Garmins id-koder for sport/steg/målsoner under er hentet fra
tredjepartprosjekter og er MEDIUM konfidens — «verifiser ved første live
push» står i runbooken. Feiler upload_workout, er det disse tabellene som
skal justeres.
"""

from __future__ import annotations

from typing import Any

_SPORT = {
    "running": {"sportTypeId": 1, "sportTypeKey": "running"},
    "strength": {"sportTypeId": 5, "sportTypeKey": "strength_training"},
    # HIIT pushes som løpeøkt med intervallsteg — mest kompatible målvalg
    "hiit": {"sportTypeId": 1, "sportTypeKey": "running"},
}

_STEP_TYPE = {
    "warmup": {"stepTypeId": 1, "stepTypeKey": "warmup"},
    "cooldown": {"stepTypeId": 2, "stepTypeKey": "cooldown"},
    "interval": {"stepTypeId": 3, "stepTypeKey": "interval"},
    "recovery": {"stepTypeId": 4, "stepTypeKey": "recovery"},
    "rest": {"stepTypeId": 5, "stepTypeKey": "rest"},
    "repeat": {"stepTypeId": 6, "stepTypeKey": "repeat"},
}

_END_TIME = {"conditionTypeId": 2, "conditionTypeKey": "time"}
_END_REPS = {"conditionTypeId": 10, "conditionTypeKey": "reps"}
_END_LAP = {"conditionTypeId": 1, "conditionTypeKey": "lap.button"}

_TARGET_NONE = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
_TARGET_HR_ZONE = {
    "workoutTargetTypeId": 4,
    "workoutTargetTypeKey": "heart.rate.zone",
}


class WorkoutSpecError(ValueError):
    pass


def _target(step: dict) -> dict:
    target = step.get("target")
    if not target:
        return {"targetType": _TARGET_NONE}
    if target.startswith("hr_zone_"):
        return {"targetType": _TARGET_HR_ZONE, "zoneNumber": int(target[-1])}
    raise WorkoutSpecError(f"ukjent target: {target!r} (bruk hr_zone_1..5)")


def _timed_step(order: int, kind: str, seconds: float, step: dict) -> dict:
    return {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": _STEP_TYPE[kind],
        "endCondition": _END_TIME,
        "endConditionValue": seconds,
        **_target(step),
    }


def _exercise_group(order: int, step: dict) -> dict:
    for key in ("exercise", "sets", "reps"):
        if not step.get(key):
            raise WorkoutSpecError(f"exercise-steg mangler {key!r}")
    weight = step.get("weight_kg")
    exercise_step = {
        "type": "ExecutableStepDTO",
        "stepOrder": order + 1,
        "stepType": _STEP_TYPE["interval"],
        "endCondition": _END_REPS,
        "endConditionValue": int(step["reps"]),
        "targetType": _TARGET_NONE,
        "category": step["exercise"],
        "exerciseName": step.get("exercise_name") or step["exercise"],
        # Garmin bruker gram
        "weightValue": round(weight * 1000) if weight else None,
    }
    children = [exercise_step]
    if step.get("rest_s"):
        children.append(
            {
                "type": "ExecutableStepDTO",
                "stepOrder": order + 2,
                "stepType": _STEP_TYPE["rest"],
                "endCondition": _END_TIME,
                "endConditionValue": step["rest_s"],
                "targetType": _TARGET_NONE,
            }
        )
    return {
        "type": "RepeatGroupDTO",
        "stepOrder": order,
        "stepType": _STEP_TYPE["repeat"],
        "numberOfIterations": int(step["sets"]),
        "workoutSteps": children,
    }


def _interval_group(order: int, step: dict) -> dict:
    for key in ("work_s", "repeats"):
        if not step.get(key):
            raise WorkoutSpecError(f"interval-steg mangler {key!r}")
    work = {
        "type": "ExecutableStepDTO",
        "stepOrder": order + 1,
        "stepType": _STEP_TYPE["interval"],
        "endCondition": _END_TIME,
        "endConditionValue": step["work_s"],
        **_target(step),
    }
    children = [work]
    if step.get("rest_s"):
        children.append(
            {
                "type": "ExecutableStepDTO",
                "stepOrder": order + 2,
                "stepType": _STEP_TYPE["recovery"],
                "endCondition": _END_TIME,
                "endConditionValue": step["rest_s"],
                "targetType": _TARGET_NONE,
            }
        )
    return {
        "type": "RepeatGroupDTO",
        "stepOrder": order,
        "stepType": _STEP_TYPE["repeat"],
        "numberOfIterations": int(step["repeats"]),
        "workoutSteps": children,
    }


def build_garmin_workout(spec: dict) -> dict:
    name = spec.get("name")
    sport = spec.get("sport")
    steps = spec.get("steps")
    if not name or sport not in _SPORT or not steps:
        raise WorkoutSpecError("spec krever name, sport (running|strength|hiit) og minst ett steg")
    out_steps: list[dict[str, Any]] = []
    order = 1
    for step in steps:
        kind = step.get("kind")
        if kind in ("warmup", "cooldown", "steady"):
            seconds = (step.get("duration_min") or 0) * 60
            if not seconds:
                raise WorkoutSpecError(f"{kind}-steg mangler duration_min")
            step_kind = "interval" if kind == "steady" else kind
            out_steps.append(_timed_step(order, step_kind, seconds, step))
            order += 1
        elif kind == "interval":
            group = _interval_group(order, step)
            out_steps.append(group)
            order += 1 + len(group["workoutSteps"])
        elif kind == "exercise":
            group = _exercise_group(order, step)
            out_steps.append(group)
            order += 1 + len(group["workoutSteps"])
        else:
            raise WorkoutSpecError(f"ukjent steg-kind: {kind!r}")

    sport_type = _SPORT[sport]
    return {
        "workoutName": name,
        "sportType": sport_type,
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": sport_type,
                "workoutSteps": out_steps,
            }
        ],
    }
