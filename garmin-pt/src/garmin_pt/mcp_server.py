"""Kuratert MCP-server: 8 verktøy som svarer med konklusjoner, ikke datadumper.

Leseverktøyene åpner SQLite read-only og rører aldri nettet.
push_workout_to_garmin er det ENESTE verktøyet som kaller Garmin live
(skriv er sjeldne — ukentlig — så rate limiting er ikke et problem der).
Alle svar bærer `conclusion` (norsk) og `data_basis`.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import date as Date
from datetime import datetime, timedelta

from mcp.server.mcpserver import MCPServer

from . import db
from .analytics import load as a_load
from .analytics import markers as a_markers
from .analytics import readiness as a_readiness
from .analytics import strengthprog as a_strength
from .config import Settings, load_settings
from .garmin import auth
from .garmin.client import AuthError, GarminUnavailable, RateLimited
from .ingest.strength import muscle_group_for
from .workouts import WorkoutSpecError, build_garmin_workout

mcp = MCPServer("garmin-pt")


def _settings() -> Settings:
    return load_settings()


def _resolve_date(date: str) -> Date:
    return Date.today() if date in ("", "today") else Date.fromisoformat(date)


def _ro_conn(settings: Settings) -> sqlite3.Connection | None:
    if not settings.db_path.exists():
        return None
    return db.connect(settings.db_path, read_only=True)


_NO_DATA = {
    "status": "no_data",
    "conclusion": (
        "Ingen lokal database ennå — kjør 'garmin-pt ingest --backfill 365' lokalt først."
    ),
}

_RECOMMENDATION_TEXT = {
    "run_plan": "Kjør planen som oppsatt.",
    "reduce_intensity": "Behold økten, men kutt toppsettene / reduser intensitet ~10 %.",
    "swap_to_easy": "Flytt dagens harde økt — kjør sone 2 eller mobilitet i stedet.",
    "add_load": "God kapasitet: legg på +1 sett eller +2,5 kg i dag.",
    "forced_easy_week": "Belastningsforholdet er for høyt — tvungen lettuke.",
    "calibrating": ("Kalibrerer fortsatt: for få netter med HRV-baseline til å gi råd."),
}


@mcp.tool()
def get_readiness(date: str = "today") -> dict:
    """Dagens readiness: HRV mot egen 60-dagers baseline, søvn, hvilepuls,
    Body Battery og subjektiv rapport → én anbefaling."""
    settings = _settings()
    conn = _ro_conn(settings)
    if conn is None:
        return dict(_NO_DATA)
    try:
        day = _resolve_date(date)
        sig = a_readiness.gather_signals(conn, settings.readiness, day)
        decision = a_readiness.evaluate(sig, settings.readiness, settings.load)

        parts = []
        if sig.hrv_z is not None:
            retning = "under" if sig.hrv_z < 0 else "over"
            window = settings.readiness.baseline_window_days
            parts.append(f"HRV {abs(sig.hrv_z):.1f} SD {retning} {window}d-baseline")
        if sig.sleep_h is not None:
            parts.append(f"søvn {sig.sleep_h} t")
        rhr_flag = settings.readiness.rhr_dev_flag_bpm
        if sig.rhr_dev_bpm is not None and abs(sig.rhr_dev_bpm) >= rhr_flag:
            parts.append(f"hvilepuls {sig.rhr_dev_bpm:+.0f} slag mot baseline")
        detail = "; ".join(parts) if parts else "begrenset datagrunnlag"
        conclusion = f"{detail}. {_RECOMMENDATION_TEXT[decision.recommendation]}"

        basis = [
            f"{sig.hrv_baseline_n} netter HRV i {settings.readiness.baseline_window_days}d-baseline"
        ]
        basis.append(
            "subjektiv rapport fra i dag" if sig.subjective else "ingen subjektiv rapport i dag"
        )
        if sig.acwr is not None:
            basis.append(f"ACWR {sig.acwr} fra siste 28 dager")
        return {
            "date": day.isoformat(),
            "status": decision.status,
            "readiness_score": decision.score,
            "recommendation": decision.recommendation,
            "conclusion": conclusion,
            "signals": asdict(sig),
            "rules_fired": decision.rules_fired,
            "data_basis": "; ".join(basis),
        }
    finally:
        conn.close()


@mcp.tool()
def get_training_load(weeks: int = 6) -> dict:
    """Ukentlig volum, TRIMP og tid per HR-sone, pluss akutt:kronisk-forhold
    og monotoni."""
    settings = _settings()
    conn = _ro_conn(settings)
    if conn is None:
        return dict(_NO_DATA)
    try:
        today = Date.today()
        weekly = a_load.weekly_load(conn, weeks, today)
        acwr = a_load.acwr(a_load.daily_trimp_map(conn, today), today)
        monotony = a_load.monotony_7d(conn, today)
        sessions = sum(w["sessions"] for w in weekly)

        if acwr is None:
            acwr_flag = "calibrating"
        elif acwr > settings.load.acwr_ceiling:
            acwr_flag = "too_high"
        elif acwr < settings.load.acwr_floor:
            acwr_flag = "low"
        else:
            acwr_flag = "ok"
        flags = {
            "too_high": "for høyt — lettuke",
            "low": "lavt — rom for mer",
            "ok": "i sunn sone",
            "calibrating": "kalibrerer",
        }
        if monotony is None:
            mono_txt = "; monotoni ikke beregnbar (uniform/tom uke)"
        else:
            mono_flag = " (flagg: for jevnt)" if monotony > settings.load.monotony_flag else ""
            mono_txt = f"; monotoni {monotony}{mono_flag}"
        conclusion = (
            f"{sessions} økter siste {weeks} uker. "
            f"ACWR {acwr if acwr is not None else '–'} ({flags[acwr_flag]}){mono_txt}."
        )
        return {
            "conclusion": conclusion,
            "acwr": acwr,
            "acwr_flag": acwr_flag,
            "monotony_7d": monotony,
            "weekly": weekly,
            "data_basis": f"{sessions} økter siste {weeks} uker; TRIMP=Edwards fra tid-i-sone "
            "(fallback: Garmin-load, deretter varighet)",
        }
    finally:
        conn.close()


@mcp.tool()
def get_strength_progression(
    muscle_group: str | None = None, exercise: str | None = None, weeks: int = 12
) -> dict:
    """e1RM-trend (Epley) og volumtrend per øvelse. Klokkedata uten vekt
    ekskluderes fra e1RM men telles i volum; superseded rader ignoreres."""
    settings = _settings()
    conn = _ro_conn(settings)
    if conn is None:
        return dict(_NO_DATA)
    try:
        result = a_strength.progression(
            conn,
            settings.e1rm,
            Date.today(),
            muscle_group=muscle_group,
            exercise=exercise,
            weeks=weeks,
        )
        exercises = result["exercises"]
        if not exercises:
            return {
                "conclusion": "Ingen styrkesett i perioden — er styrkeøktene "
                "logget med øvelsesprofil på klokka?",
                "exercises": [],
                "data_basis": f"0 sett siste {weeks} uker",
            }
        movers = [e for e in exercises if e.get("e1rm_slope_kg_per_week") is not None]
        movers.sort(key=lambda e: e["e1rm_slope_kg_per_week"], reverse=True)
        bits = []
        if movers:
            top = movers[0]
            bits.append(
                f"{top['exercise']}: e1RM {top['e1rm_first']}→{top['e1rm_last']} kg "
                f"({top['e1rm_slope_kg_per_week']:+.1f} kg/uke)"
            )
            flat = [e["exercise"] for e in movers if abs(e["e1rm_slope_kg_per_week"]) < 0.1]
            if flat:
                bits.append(f"flat progresjon: {', '.join(flat[:3])}")
        thin = [e["exercise"] for e in exercises if "note" in e]
        if thin:
            bits.append(f"for få målinger: {', '.join(thin[:3])}")
        return {
            "conclusion": ". ".join(bits) + ".",
            "exercises": exercises,
            "data_basis": (
                f"{result['total_sets']} sett siste {weeks} uker; "
                "garmin-sett + manuelle korrigeringer, superseded ekskludert"
            ),
        }
    finally:
        conn.close()


@mcp.tool()
def get_recent_sessions(n: int = 10) -> dict:
    """Siste økter med planlagt-vs-utført-avvik der plan-rader finnes."""
    settings = _settings()
    conn = _ro_conn(settings)
    if conn is None:
        return dict(_NO_DATA)
    try:
        acts = conn.execute(
            "SELECT * FROM activities ORDER BY date DESC, start_time DESC LIMIT ?",
            (n,),
        ).fetchall()
        sessions = []
        matched = 0
        for a in acts:
            plan = conn.execute(
                "SELECT id, planned_type FROM plan WHERE date = ? ORDER BY id LIMIT 1",
                (a["date"],),
            ).fetchone()
            if plan is None:
                deviation = "ingen plan registrert"
                planned = None
            else:
                matched += 1
                planned = {"type": plan["planned_type"], "source": f"plan#{plan['id']}"}
                same = (
                    plan["planned_type"].startswith("strength")
                    and a["activity_type"].startswith(("strength", "indoor_strength"))
                ) or plan["planned_type"] in (a["activity_type"], "zone2", "hiit")
                deviation = (
                    "utført som planlagt"
                    if same
                    else f"plan: {plan['planned_type']} → utført {a['activity_type']}"
                )
            sessions.append(
                {
                    "date": a["date"],
                    "type": a["activity_type"],
                    "name": a["name"],
                    "duration_min": round(a["duration_s"] / 60) if a["duration_s"] else None,
                    "trimp": a["trimp"],
                    "avg_hr": a["avg_hr"],
                    "planned": planned,
                    "deviation": deviation,
                }
            )
        return {
            "conclusion": f"{len(sessions)} siste økter; {matched} hadde matchende planrad.",
            "sessions": sessions,
            "data_basis": f"{len(sessions)} siste aktiviteter fra klokka",
        }
    finally:
        conn.close()


@mcp.tool()
def get_fitness_markers() -> dict:
    """VO2max, terskelpuls, treningsstatus, hvilepuls- og vekttrend."""
    settings = _settings()
    conn = _ro_conn(settings)
    if conn is None:
        return dict(_NO_DATA)
    try:
        out = a_markers.fitness_markers(conn, Date.today())
        bits = []
        if out["vo2max"]:
            delta = out["vo2max"]["delta_90d"]
            trend = (
                "stabil"
                if delta is None or abs(delta) < 1.0
                else ("opp " if delta > 0 else "ned ") + f"{abs(delta)}"
            )
            bits.append(f"VO2max {out['vo2max']['current']} ({trend} mot 90d)")
        if out["resting_hr"] and out["resting_hr"]["avg_7d"] is not None:
            diff = out["resting_hr"]["avg_7d"] - (out["resting_hr"]["baseline_60d"] or 0)
            bits.append(f"hvilepuls 7d-snitt {out['resting_hr']['avg_7d']} ({diff:+.1f} mot 60d)")
        if out["training_status"]:
            bits.append(f"status {out['training_status']}")
        out["conclusion"] = (
            "; ".join(bits) + "." if bits else "For lite data for formmarkører ennå."
        )
        return out
    finally:
        conn.close()


@mcp.tool()
def log_subjective(
    sleep_feel: int,
    stress: int,
    soreness: int,
    motivation: int,
    date: str = "today",
    soreness_location: str | None = None,
    note: str | None = None,
) -> dict:
    """Dagens 15-sekunders selvrapport (alle verdier 1–5; 5 = best søvn/mest
    stress/mest støl/høyest motivasjon)."""
    values = {
        "sleep_feel": sleep_feel,
        "stress": stress,
        "soreness": soreness,
        "motivation": motivation,
    }
    for key, v in values.items():
        if not isinstance(v, int) or not 1 <= v <= 5:
            return {"error": "invalid_value", "conclusion": f"{key} må være heltall 1–5."}
    settings = _settings()
    day = _resolve_date(date).isoformat()
    conn = db.connect(settings.db_path)
    try:
        db.upsert(
            conn,
            "subjective",
            {**values, "date": day, "soreness_location": soreness_location, "note": note},
            ["date"],
            touch="updated_at",
        )
        conn.commit()
        streak = 0
        d = _resolve_date(date)
        while conn.execute("SELECT 1 FROM subjective WHERE date = ?", (d.isoformat(),)).fetchone():
            streak += 1
            d -= timedelta(days=1)
        extra = (
            f" Stølhet {soreness} ({soreness_location}) tas med i readiness."
            if soreness >= 4 and soreness_location
            else ""
        )
        return {
            "stored": {**values, "date": day},
            "streak_days": streak,
            "conclusion": f"Registrert for {day}.{extra}",
        }
    finally:
        conn.close()


@mcp.tool()
def log_strength_session(date: str, exercises: list[dict], activity_id: int | None = None) -> dict:
    """Manuell logging/korrigering av styrkesett. exercises =
    [{"exercise": "BENCH_PRESS", "sets": [{"reps": 5, "weight_kg": 80,
    "rir": 2}]}]. Garmin-sett for samme aktivitet+øvelse markeres superseded
    (aldri slettet); uten aktivitet den datoen lagres rene manuelle rader."""
    settings = _settings()
    day = _resolve_date(date).isoformat()
    conn = db.connect(settings.db_path)
    try:
        if activity_id is None:
            candidates = conn.execute(
                "SELECT activity_id FROM activities WHERE date = ? AND "
                "activity_type IN ('strength_training', 'indoor_strength')",
                (day,),
            ).fetchall()
            if len(candidates) == 1:
                activity_id = candidates[0]["activity_id"]

        sets_written = 0
        superseded = 0
        for entry in exercises:
            name = str(entry.get("exercise", "")).upper().replace(" ", "_")
            sets = entry.get("sets") or []
            if not name or not sets:
                return {
                    "error": "invalid_spec",
                    "conclusion": "Hver øvelse trenger 'exercise' og minst ett sett.",
                }
            if activity_id is not None:
                cur = conn.execute(
                    "UPDATE strength_sets SET superseded = 1 "
                    "WHERE activity_id = ? AND exercise LIKE ? AND source = 'garmin' "
                    "AND superseded = 0",
                    (activity_id, f"%{name}%"),
                )
                superseded += cur.rowcount
            for i, s in enumerate(sets, start=1):
                weight = s.get("weight_kg")
                reps = s.get("reps")
                conn.execute(
                    "INSERT INTO strength_sets (activity_id, date, exercise, "
                    "muscle_group, set_index, reps, weight_kg, rir, rpe, e1rm, source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual')",
                    (
                        activity_id,
                        day,
                        name,
                        muscle_group_for(name),
                        i,
                        reps,
                        weight,
                        s.get("rir"),
                        s.get("rpe"),
                        a_strength.epley(weight, reps, settings.e1rm.epley_max_reps),
                    ),
                )
                sets_written += 1
        conn.commit()
        return {
            "sets_written": sets_written,
            "superseded_garmin_sets": superseded,
            "activity_id": activity_id,
            "conclusion": (
                f"Skrev {sets_written} manuelle sett for {day}"
                + (f", erstattet {superseded} garmin-sett" if superseded else "")
                + ("." if activity_id else " (ingen klokkeøkt matchet — rene manuelle rader).")
            ),
        }
    finally:
        conn.close()


@mcp.tool()
def push_workout_to_garmin(workout: dict, schedule_date: str | None = None) -> dict:
    """Bygg strukturert økt og legg den i Garmin Connect-kalenderen.
    Eneste verktøy som kaller Garmin live."""
    settings = _settings()
    try:
        payload = build_garmin_workout(workout)
    except WorkoutSpecError as e:
        return {"error": "invalid_spec", "conclusion": str(e)}

    try:
        client = auth.login(settings, interactive=False)
        resp = client.upload_workout(payload) or {}
        workout_id = resp.get("workoutId") or resp.get("workout_id")
        scheduled_for = None
        if schedule_date and workout_id:
            client.schedule_workout(workout_id, schedule_date)
            scheduled_for = schedule_date
    except AuthError:
        return {
            "error": "auth_expired",
            "action": "kjør 'garmin-pt auth' lokalt og prøv igjen",
            "conclusion": "Garmin-innloggingen er utløpt — økta ble ikke pushet.",
        }
    except RateLimited:
        return {
            "error": "rate_limited",
            "action": "vent noen minutter og prøv igjen",
            "conclusion": "Garmin rate-limiter akkurat nå — økta ble ikke pushet.",
        }
    except GarminUnavailable as e:
        return {"error": "garmin_unavailable", "conclusion": f"Garmin utilgjengelig: {e}"}

    conn = db.connect(settings.db_path)
    try:
        cur = conn.execute(
            "INSERT INTO plan (date, planned_type, planned_detail, garmin_workout_id, "
            "pt_reasoning) VALUES (?, ?, ?, ?, ?)",
            (
                schedule_date or datetime.now().date().isoformat(),
                workout.get("sport", "unknown"),
                json.dumps(workout, ensure_ascii=False),
                str(workout_id) if workout_id else None,
                workout.get("reasoning"),
            ),
        )
        conn.commit()
        plan_id = cur.lastrowid
    finally:
        conn.close()
    return {
        "garmin_workout_id": workout_id,
        "scheduled_for": scheduled_for,
        "plan_id": plan_id,
        "conclusion": (
            f"Økt '{workout.get('name')}' lastet opp"
            + (f" og lagt i kalenderen {scheduled_for}." if scheduled_for else ".")
        ),
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
