import pytest

from garmin_pt.workouts import WorkoutSpecError, build_garmin_workout


def test_zone2_run():
    payload = build_garmin_workout(
        {
            "name": "Sone 2, 60 min",
            "sport": "running",
            "steps": [
                {"kind": "warmup", "duration_min": 10, "target": "hr_zone_1"},
                {"kind": "steady", "duration_min": 60, "target": "hr_zone_2"},
            ],
        }
    )
    assert payload["workoutName"] == "Sone 2, 60 min"
    assert payload["sportType"]["sportTypeKey"] == "running"
    steps = payload["workoutSegments"][0]["workoutSteps"]
    assert len(steps) == 2
    assert steps[0]["stepType"]["stepTypeKey"] == "warmup"
    assert steps[1]["endConditionValue"] == 3600
    assert steps[1]["zoneNumber"] == 2


def test_norwegian_4x4_hiit():
    payload = build_garmin_workout(
        {
            "name": "4x4 HIIT",
            "sport": "hiit",
            "steps": [
                {"kind": "warmup", "duration_min": 10, "target": "hr_zone_1"},
                {
                    "kind": "interval",
                    "work_s": 240,
                    "rest_s": 180,
                    "repeats": 4,
                    "target": "hr_zone_5",
                },
                {"kind": "cooldown", "duration_min": 5},
            ],
        }
    )
    group = payload["workoutSegments"][0]["workoutSteps"][1]
    assert group["type"] == "RepeatGroupDTO"
    assert group["numberOfIterations"] == 4
    work, recovery = group["workoutSteps"]
    assert work["endConditionValue"] == 240
    assert work["zoneNumber"] == 5
    assert recovery["stepType"]["stepTypeKey"] == "recovery"
    assert recovery["endConditionValue"] == 180


def test_strength_session():
    payload = build_garmin_workout(
        {
            "name": "Økt A underkropp+push",
            "sport": "strength",
            "steps": [
                {
                    "kind": "exercise",
                    "exercise": "SQUAT",
                    "sets": 4,
                    "reps": 5,
                    "weight_kg": 100,
                    "rest_s": 180,
                },
                {
                    "kind": "exercise",
                    "exercise": "BENCH_PRESS",
                    "sets": 4,
                    "reps": 6,
                    "weight_kg": 80,
                    "rest_s": 150,
                },
            ],
        }
    )
    assert payload["sportType"]["sportTypeKey"] == "strength_training"
    squat = payload["workoutSegments"][0]["workoutSteps"][0]
    assert squat["numberOfIterations"] == 4
    ex, rest = squat["workoutSteps"]
    assert ex["category"] == "SQUAT"
    assert ex["endConditionValue"] == 5
    assert ex["weightValue"] == 100000  # gram
    assert rest["endConditionValue"] == 180


def test_bodyweight_exercise_without_weight():
    payload = build_garmin_workout(
        {
            "name": "Trekk",
            "sport": "strength",
            "steps": [{"kind": "exercise", "exercise": "PULL_UP", "sets": 3, "reps": 8}],
        }
    )
    ex = payload["workoutSegments"][0]["workoutSteps"][0]["workoutSteps"][0]
    assert ex["weightValue"] is None


@pytest.mark.parametrize(
    "spec",
    [
        {},
        {"name": "x", "sport": "yoga", "steps": [{"kind": "steady", "duration_min": 10}]},
        {"name": "x", "sport": "running", "steps": [{"kind": "steady"}]},
        {"name": "x", "sport": "running", "steps": [{"kind": "teleport"}]},
        {"name": "x", "sport": "strength", "steps": [{"kind": "exercise", "exercise": "SQUAT"}]},
        {
            "name": "x",
            "sport": "running",
            "steps": [{"kind": "steady", "duration_min": 10, "target": "watts_300"}],
        },
    ],
)
def test_invalid_specs_raise(spec):
    with pytest.raises(WorkoutSpecError):
        build_garmin_workout(spec)
