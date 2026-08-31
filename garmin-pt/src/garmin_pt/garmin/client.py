"""Tynn wrapper rundt python-garminconnect — DEN ENESTE modulen som importerer
biblioteket. Endrer Garmin API-et seg, er det denne filen som fikses; resten av
koden (og testenes FakeGarminClient) avhenger bare av GarminClientProtocol.

Verifisert mot garminconnect==0.3.11 (2026-08-31): get_hrv_data, get_sleep_data,
get_rhr_day, get_user_summary, get_daily_weigh_ins, get_activities,
get_activity_exercise_sets, get_training_status, get_max_metrics,
upload_workout, schedule_workout.
"""

from __future__ import annotations

from typing import Any, Protocol


class RateLimited(Exception):
    """Garmin svarte 429 — ingest skal backe av og resume neste kjøring."""


class AuthError(Exception):
    """Innlogging/token avvist — krever `garmin-pt auth` lokalt."""


class GarminUnavailable(Exception):
    """Nettverks-/tjenestefeil som ikke er auth eller rate limiting."""


class GarminClientProtocol(Protocol):
    def hrv_day(self, date: str) -> dict | None: ...
    def sleep_day(self, date: str) -> dict | None: ...
    def rhr_day(self, date: str) -> dict | None: ...
    def user_summary(self, date: str) -> dict | None: ...
    def weigh_ins(self, date: str) -> dict | None: ...
    def activities(self, start: int, limit: int) -> list[dict]: ...
    def exercise_sets(self, activity_id: int) -> dict | None: ...
    def training_status(self, date: str) -> dict | None: ...
    def max_metrics(self, date: str) -> dict | list | None: ...
    def upload_workout(self, payload: dict) -> dict: ...
    def schedule_workout(self, workout_id: int | str, date: str) -> dict: ...


class GarminClient:
    """Oversetter bibliotekets exceptions til de typede feilene over.
    404 for en dag uten data er normalt og blir None."""

    def __init__(self, api: Any) -> None:
        self._api = api

    def _call(self, fn, *args):
        from garminconnect import (
            GarminConnectAuthenticationError,
            GarminConnectConnectionError,
            GarminConnectNotFoundError,
            GarminConnectTooManyRequestsError,
            HTTPError,
        )

        try:
            return fn(*args)
        except GarminConnectTooManyRequestsError as e:
            raise RateLimited(str(e)) from e
        except GarminConnectAuthenticationError as e:
            raise AuthError(str(e)) from e
        except GarminConnectNotFoundError:
            return None
        except GarminConnectConnectionError as e:
            raise GarminUnavailable(str(e)) from e
        except HTTPError as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status == 429:
                raise RateLimited(str(e)) from e
            if status in (401, 403):
                raise AuthError(str(e)) from e
            if status == 404:
                return None
            raise GarminUnavailable(str(e)) from e

    def hrv_day(self, date: str) -> dict | None:
        return self._call(self._api.get_hrv_data, date)

    def sleep_day(self, date: str) -> dict | None:
        return self._call(self._api.get_sleep_data, date)

    def rhr_day(self, date: str) -> dict | None:
        return self._call(self._api.get_rhr_day, date)

    def user_summary(self, date: str) -> dict | None:
        return self._call(self._api.get_user_summary, date)

    def weigh_ins(self, date: str) -> dict | None:
        return self._call(self._api.get_daily_weigh_ins, date)

    def activities(self, start: int, limit: int) -> list[dict]:
        result = self._call(self._api.get_activities, start, limit)
        return result if isinstance(result, list) else []

    def exercise_sets(self, activity_id: int) -> dict | None:
        return self._call(self._api.get_activity_exercise_sets, activity_id)

    def training_status(self, date: str) -> dict | None:
        return self._call(self._api.get_training_status, date)

    def max_metrics(self, date: str) -> dict | list | None:
        return self._call(self._api.get_max_metrics, date)

    def upload_workout(self, payload: dict) -> dict:
        return self._call(self._api.upload_workout, payload)

    def schedule_workout(self, workout_id: int | str, date: str) -> dict:
        return self._call(self._api.schedule_workout, workout_id, date)
