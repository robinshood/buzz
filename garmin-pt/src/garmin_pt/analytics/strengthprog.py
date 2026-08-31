"""Styrkeprogresjon: Epley e1RM, ukestrender per øvelse, volumtrend.

Klokkedata mangler ofte vekt (og reps kan være gjettet) — alt her degraderer
pent og oppgir datagrunnlaget sitt eksplisitt.
"""

from __future__ import annotations

import sqlite3
import statistics
from datetime import date as Date

from ..config import E1rmCfg


def epley(weight_kg: float | None, reps: int | None, max_reps: int = 12) -> float | None:
    """e1RM = vekt × (1 + reps/30). None uten vekt/reps eller ved reps > taket
    (høyrepssett er for upresise for 1RM-estimat, men teller i volum)."""
    if weight_kg is None or reps is None or reps <= 0 or reps > max_reps:
        return None
    return round(weight_kg * (1 + reps / 30.0), 1)


def _slope_per_week(points: list[tuple[int, float]]) -> float | None:
    """Minste kvadraters stigning (enhet/uke) over (ukeindeks, verdi)."""
    if len(points) < 2:
        return None
    xs, ys = zip(*points, strict=True)
    if len(set(xs)) < 2:
        return None
    slope, _ = statistics.linear_regression(xs, ys)
    return slope


def _trend_label(slope: float | None, mean: float) -> str:
    """>±1 % av nivået per uke regnes som reell endring."""
    if slope is None or mean <= 0:
        return "unknown"
    rel = slope / mean
    if rel > 0.01:
        return "up"
    if rel < -0.01:
        return "down"
    return "flat"


def progression(
    conn: sqlite3.Connection,
    cfg: E1rmCfg,
    asof: Date,
    muscle_group: str | None = None,
    exercise: str | None = None,
    weeks: int = 12,
) -> dict:
    """Per-øvelse e1RM- og volumtrend siste `weeks` uker. superseded-rader
    (garmin-sett erstattet av manuell korreksjon) er alltid ekskludert."""
    sql = (
        "SELECT date, exercise, muscle_group, reps, weight_kg, e1rm, "
        "  date(date, 'weekday 0', '-6 days') AS week_start "
        "FROM strength_sets WHERE superseded = 0 "
        "AND date > date(?, ?) AND date <= ?"
    )
    params: list = [asof.isoformat(), f"-{weeks * 7} days", asof.isoformat()]
    if muscle_group:
        sql += " AND muscle_group = ?"
        params.append(muscle_group.lower())
    if exercise:
        sql += " AND exercise = ?"
        params.append(exercise.upper())
    rows = conn.execute(sql + " ORDER BY date", params).fetchall()

    by_exercise: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        by_exercise.setdefault(r["exercise"], []).append(r)

    out = []
    for name, sets in sorted(by_exercise.items()):
        sessions = sorted({r["date"] for r in sets})
        complete = [r for r in sets if r["weight_kg"] is not None and r["reps"]]
        pct_complete = round(100 * len(complete) / len(sets)) if sets else 0

        weekly_best: dict[str, float] = {}
        weekly_tonnage: dict[str, float] = {}
        for r in sets:
            wk = r["week_start"]
            if r["e1rm"] is not None:
                weekly_best[wk] = max(weekly_best.get(wk, 0.0), r["e1rm"])
            if r["weight_kg"] is not None and r["reps"]:
                weekly_tonnage[wk] = weekly_tonnage.get(wk, 0.0) + r["weight_kg"] * r["reps"]

        e1rm_points = sorted(weekly_best.items())
        entry: dict = {
            "exercise": name,
            "muscle_group": sets[0]["muscle_group"],
            "data_basis": (
                f"{len(sessions)} økter, {len(sets)} sett, {pct_complete} % med vekt+reps"
            ),
        }
        if len(e1rm_points) >= cfg.trend_min_points:
            # ukeindeks fra faktisk kalenderuke, ikke listeposisjon
            first_week = Date.fromisoformat(e1rm_points[0][0])
            pts = [
                ((Date.fromisoformat(wk) - first_week).days // 7, val) for wk, val in e1rm_points
            ]
            slope = _slope_per_week(pts)
            entry.update(
                e1rm_first=e1rm_points[0][1],
                e1rm_last=e1rm_points[-1][1],
                e1rm_slope_kg_per_week=round(slope, 2) if slope is not None else None,
                weekly_best_e1rm=[{"week_start": wk, "e1rm": val} for wk, val in e1rm_points],
            )
        else:
            entry.update(
                e1rm_first=None,
                e1rm_last=e1rm_points[-1][1] if e1rm_points else None,
                e1rm_slope_kg_per_week=None,
                weekly_best_e1rm=[{"week_start": wk, "e1rm": val} for wk, val in e1rm_points],
                note=f"for få uker med e1RM ({len(e1rm_points)} < {cfg.trend_min_points})",
            )
        tonnage_points = sorted(weekly_tonnage.items())
        if len(tonnage_points) >= 2:
            first_week = Date.fromisoformat(tonnage_points[0][0])
            pts = [
                ((Date.fromisoformat(wk) - first_week).days // 7, val) for wk, val in tonnage_points
            ]
            entry["volume_trend"] = _trend_label(
                _slope_per_week(pts), statistics.mean(v for _, v in tonnage_points)
            )
        else:
            entry["volume_trend"] = "unknown"
        out.append(entry)
    return {"exercises": out, "total_sets": len(rows)}
