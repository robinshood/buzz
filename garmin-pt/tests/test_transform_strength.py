from conftest import load_fixture

from garmin_pt.ingest.strength import muscle_group_for, strength_rows


def test_full_session_rows():
    raw = load_fixture("exercise_sets_full.json")
    rows = strength_rows(987654322, "2026-08-28", raw)
    # 5 sett i payload, 2 er REST → 3 aktive
    assert len(rows) == 3
    assert [r["set_index"] for r in rows] == [1, 2, 3]
    first = rows[0]
    assert first["exercise"] == "BARBELL_BENCH_PRESS"
    assert first["muscle_group"] == "chest"
    assert first["weight_kg"] == 80.0  # 80000 g → kg
    assert first["reps"] == 5
    assert first["e1rm"] == 93.3
    # settet med lavere sannsynlighets-LUNGE skal velge SQUAT
    assert rows[2]["exercise"] == "BARBELL_BACK_SQUAT"
    assert rows[2]["muscle_group"] == "legs"


def test_missing_weight_and_unknown_exercise():
    raw = load_fixture("exercise_sets_missing_weight.json")
    rows = strength_rows(987654323, "2026-08-27", raw)
    assert len(rows) == 3
    pullup, obscure, empty = rows
    # kroppsvektøvelse: reps men ingen vekt → e1rm None, volum-telling mulig
    assert pullup["exercise"] == "PULL_UP"
    assert pullup["muscle_group"] == "back"
    assert pullup["weight_kg"] is None
    assert pullup["e1rm"] is None
    assert pullup["reps"] == 8
    # ukjent kategori beholder rånavn uten muskelgruppe
    assert obscure["exercise"] == "OBSCURE_MOVEMENT_XYZ"
    assert obscure["muscle_group"] is None
    assert obscure["reps"] is None
    # tom exercises-liste
    assert empty["exercise"] == "UNKNOWN"
    assert empty["weight_kg"] == 24.0


def test_muscle_group_ordering_leg_curl_before_curl():
    assert muscle_group_for("LEG_CURL") == "legs"
    assert muscle_group_for("BICEPS_CURL") == "biceps"
    assert muscle_group_for("TRICEPS_EXTENSION") == "triceps"
    assert muscle_group_for("FARMERS_CARRY") == "core"
    assert muscle_group_for(None) is None


def test_weight_unit_guard():
    # < 400 tolkes som allerede-kg (vern mot enhetsdrift)
    raw = {
        "exerciseSets": [
            {
                "exercises": [{"category": "SQUAT", "name": None, "probability": 99.0}],
                "repetitionCount": 5,
                "weight": 102.5,
                "setType": "ACTIVE",
            }
        ]
    }
    rows = strength_rows(1, "2026-08-27", raw)
    assert rows[0]["weight_kg"] == 102.5
