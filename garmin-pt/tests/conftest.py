"""Delte testfixtures. Nettverk er HARDT blokkert i alle tester."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise RuntimeError("Nettverk er blokkert i tester")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def db_conn(tmp_path):
    from garmin_pt import db

    conn = db.connect(tmp_path / "test.db")
    yield conn
    conn.close()


@pytest.fixture
def settings(tmp_path):
    from garmin_pt.config import Settings

    return Settings(data_dir=tmp_path / "data")


class FakeGarminClient:
    """Oppfyller GarminClientProtocol mot fixture-filer, uten nettverk.

    fail_queue[endpoint] er en kø som konsumeres per kall: et Exception-element
    raises, None serverer normalt — slik kan man feile på N-te kall.
    """

    def __init__(self):
        self.calls: list[tuple] = []
        self.fail_queue: dict[str, list[Exception | None]] = {}
        self.uploaded_workouts: list[dict] = []
        self.scheduled: list[tuple] = []
        self.data = {
            "hrv_day": load_fixture("hrv_day.json"),
            "sleep_day": load_fixture("sleep_day.json"),
            "rhr_day": load_fixture("rhr_day.json"),
            "user_summary": load_fixture("user_summary.json"),
            "weigh_ins": load_fixture("weigh_ins.json"),
            "activities": load_fixture("activities_page.json"),
            "exercise_sets": {987654322: load_fixture("exercise_sets_full.json")},
            "training_status": load_fixture("training_status.json"),
            "max_metrics": load_fixture("max_metrics.json"),
        }

    def _serve(self, name: str, *args):
        self.calls.append((name, *args))
        queue = self.fail_queue.get(name)
        if queue:
            exc = queue.pop(0)
            if exc is not None:
                raise exc
        return None

    def hrv_day(self, date):
        self._serve("hrv_day", date)
        return self.data["hrv_day"]

    def sleep_day(self, date):
        self._serve("sleep_day", date)
        return self.data["sleep_day"]

    def rhr_day(self, date):
        self._serve("rhr_day", date)
        return self.data["rhr_day"]

    def user_summary(self, date):
        self._serve("user_summary", date)
        return self.data["user_summary"]

    def weigh_ins(self, date):
        self._serve("weigh_ins", date)
        return self.data["weigh_ins"]

    def activities(self, start, limit):
        self._serve("activities", start, limit)
        return self.data["activities"][start : start + limit]

    def exercise_sets(self, activity_id):
        self._serve("exercise_sets", activity_id)
        return self.data["exercise_sets"].get(activity_id)

    def training_status(self, date):
        self._serve("training_status", date)
        return self.data["training_status"]

    def max_metrics(self, date):
        self._serve("max_metrics", date)
        return self.data["max_metrics"]

    def upload_workout(self, payload):
        self._serve("upload_workout")
        self.uploaded_workouts.append(payload)
        return {"workoutId": 4242}

    def schedule_workout(self, workout_id, date):
        self._serve("schedule_workout", workout_id, date)
        self.scheduled.append((workout_id, date))
        return {"workoutScheduleId": 777}


@pytest.fixture
def fake_client():
    return FakeGarminClient()
