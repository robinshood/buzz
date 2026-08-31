from conftest import load_fixture

from garmin_pt.ingest.activities import activity_row, is_strength


def test_running_with_zones():
    raw = load_fixture("activities_page.json")[0]
    row = activity_row(raw)
    assert row["activity_id"] == 987654321
    assert row["date"] == "2026-08-29"
    assert row["activity_type"] == "running"
    assert row["avg_hr"] == 152
    assert row["hr_zone_2_s"] == 1980.0
    # Edwards: (240 + 2*1980 + 3*900 + 4*380 + 5*112.4)/60 = 4*240... regn:
    # 240 + 3960 + 2700 + 1520 + 562 = 8982 s-vektet → /60 = 149.7
    assert row["trimp"] == 149.7


def test_strength_without_hr_zones_falls_back_to_duration():
    raw = load_fixture("activities_page.json")[1]
    row = activity_row(raw)
    assert row["activity_type"] == "strength_training"
    assert is_strength(row["activity_type"])
    # ingen soner, ingen garmin_load → varighetsgulv: 3120/60 = 52 min
    assert row["trimp"] == 52.0


def test_invalid_item_returns_none():
    assert activity_row({"activityName": "uten id"}) is None
    assert activity_row({"activityId": 1, "activityType": {}}) is None
