"""Formmarkører: VO2max, terskelpuls, treningsstatus, hvilepuls- og vekttrend."""

from __future__ import annotations

import sqlite3
from datetime import date as Date


def _latest(conn: sqlite3.Connection, column: str, asof: str) -> sqlite3.Row | None:
    return conn.execute(
        f"SELECT week_start, {column} FROM metrics "
        f"WHERE {column} IS NOT NULL AND week_start <= ? "
        "ORDER BY week_start DESC LIMIT 1",
        (asof,),
    ).fetchone()


def fitness_markers(conn: sqlite3.Connection, asof: Date) -> dict:
    d = asof.isoformat()
    out: dict = {}
    basis: list[str] = []

    vo2 = _latest(conn, "vo2max", d)
    if vo2 is not None:
        old = conn.execute(
            "SELECT vo2max FROM metrics WHERE vo2max IS NOT NULL "
            "AND week_start <= date(?, '-90 days') ORDER BY week_start DESC LIMIT 1",
            (d,),
        ).fetchone()
        out["vo2max"] = {
            "current": vo2["vo2max"],
            "delta_90d": round(vo2["vo2max"] - old["vo2max"], 1) if old else None,
        }
    else:
        out["vo2max"] = None

    thr = _latest(conn, "threshold_hr", d)
    out["threshold_hr"] = thr["threshold_hr"] if thr else None
    status = _latest(conn, "training_status", d)
    out["training_status"] = status["training_status"] if status else None

    rhr = conn.execute(
        "SELECT AVG(CASE WHEN date > date(?, '-7 days') THEN resting_hr END)  AS avg_7d, "
        "       AVG(resting_hr) AS baseline_60d, "
        "       COUNT(resting_hr) AS n "
        "FROM daily WHERE date > date(?, '-60 days') AND date <= ?",
        (d, d, d),
    ).fetchone()
    out["resting_hr"] = (
        {
            "avg_7d": round(rhr["avg_7d"], 1) if rhr["avg_7d"] is not None else None,
            "baseline_60d": round(rhr["baseline_60d"], 1)
            if rhr["baseline_60d"] is not None
            else None,
        }
        if rhr and rhr["n"]
        else None
    )
    if rhr and rhr["n"]:
        basis.append(f"hvilepuls fra {rhr['n']} dager/60d")

    weight = conn.execute(
        "SELECT date, weight_kg FROM daily WHERE weight_kg IS NOT NULL AND date <= ? "
        "ORDER BY date DESC LIMIT 1",
        (d,),
    ).fetchone()
    if weight is not None:
        old_w = conn.execute(
            "SELECT weight_kg FROM daily WHERE weight_kg IS NOT NULL "
            "AND date <= date(?, '-30 days') ORDER BY date DESC LIMIT 1",
            (d,),
        ).fetchone()
        n_weighins = conn.execute(
            "SELECT COUNT(*) FROM daily WHERE weight_kg IS NOT NULL "
            "AND date > date(?, '-30 days') AND date <= ?",
            (d, d),
        ).fetchone()[0]
        out["weight"] = {
            "current_kg": weight["weight_kg"],
            "delta_30d_kg": round(weight["weight_kg"] - old_w["weight_kg"], 1) if old_w else None,
        }
        basis.append(f"vekt fra {n_weighins} veiinger/30d")
    else:
        out["weight"] = None

    n_metric_weeks = conn.execute(
        "SELECT COUNT(*) FROM metrics WHERE week_start <= ?", (d,)
    ).fetchone()[0]
    basis.insert(0, f"metrics-rader for {n_metric_weeks} uker")
    out["data_basis"] = "; ".join(basis)
    return out
