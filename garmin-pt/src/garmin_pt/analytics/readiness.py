"""Readiness: HRV z-score mot egen baseline + beslutningsregler fra config.toml.

Regelrekkefølge (første treff vinner):
  0. kalibreringsgate  — < min_baseline_days netter HRV i vinduet
  1. acwr_ceiling      — akutt:kronisk > 1.5 → tvungen lettuke
  2. hrv_red / short_sleep — z < −1.5 ELLER ≥2 korte netter → bytt til rolig
  3. hrv_yellow        — z i [−1.5, −0.5) → behold økt, reduser intensitet
  4. hrv_green_add_load — z > +1 OG lav last (acwr < floor) → legg på
  5. run_plan          — ellers
Subjektiv stølhet ≥ 4 nedgraderer add_load → run_plan.
"""

from __future__ import annotations

import sqlite3
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date as Date

from ..config import LoadCfg, ReadinessCfg
from .load import acwr, daily_trimp_map


@dataclass
class Signals:
    date: str
    hrv_ms: float | None = None
    hrv_baseline_mean: float | None = None
    hrv_baseline_sd: float | None = None
    hrv_baseline_n: int = 0
    hrv_z: float | None = None
    sleep_h: float | None = None
    sleep_score: int | None = None
    short_nights_last2: int = 0
    resting_hr: int | None = None
    rhr_baseline_mean: float | None = None
    rhr_dev_bpm: float | None = None
    body_battery_high: int | None = None
    acwr: float | None = None
    subjective: dict | None = None


@dataclass
class Decision:
    status: str  # ok | calibrating | no_data
    recommendation: str
    rules_fired: list[str] = field(default_factory=list)
    score: int | None = None


def baseline_stats(window: Sequence[float]) -> tuple[float, float, int] | None:
    """(mean, sd, n) for et baseline-vindu; None når sd ikke kan beregnes."""
    n = len(window)
    if n < 2:
        return None
    mean = statistics.mean(window)
    sd = statistics.stdev(window)
    if sd == 0:
        return None
    return mean, sd, n


def gather_signals(conn: sqlite3.Connection, r_cfg: ReadinessCfg, day: Date) -> Signals:
    d = day.isoformat()
    sig = Signals(date=d)

    today = conn.execute("SELECT * FROM daily WHERE date = ?", (d,)).fetchone()
    if today is not None:
        sig.hrv_ms = today["hrv_last_night_avg"]
        sig.resting_hr = today["resting_hr"]
        sig.sleep_score = today["sleep_score"]
        if today["sleep_duration_min"] is not None:
            sig.sleep_h = round(today["sleep_duration_min"] / 60.0, 1)
        sig.body_battery_high = today["body_battery_high"]

    window = [
        r[0]
        for r in conn.execute(
            "SELECT hrv_last_night_avg FROM daily "
            "WHERE date < ? AND date >= date(?, ?) AND hrv_last_night_avg IS NOT NULL",
            (d, d, f"-{r_cfg.baseline_window_days} days"),
        )
    ]
    stats = baseline_stats(window)
    if stats is not None:
        sig.hrv_baseline_mean, sig.hrv_baseline_sd, sig.hrv_baseline_n = (
            round(stats[0], 1),
            round(stats[1], 2),
            stats[2],
        )
        if sig.hrv_ms is not None:
            sig.hrv_z = round((sig.hrv_ms - stats[0]) / stats[1], 2)
    else:
        sig.hrv_baseline_n = len(window)

    sig.short_nights_last2 = conn.execute(
        "SELECT COUNT(*) FROM daily "
        "WHERE date IN (?, date(?, '-1 day')) AND sleep_duration_min < ?",
        (d, d, r_cfg.short_sleep_hours * 60.0),
    ).fetchone()[0]

    rhr_window = [
        r[0]
        for r in conn.execute(
            "SELECT resting_hr FROM daily "
            "WHERE date < ? AND date >= date(?, ?) AND resting_hr IS NOT NULL",
            (d, d, f"-{r_cfg.baseline_window_days} days"),
        )
    ]
    if rhr_window:
        sig.rhr_baseline_mean = round(statistics.mean(rhr_window), 1)
        if sig.resting_hr is not None:
            sig.rhr_dev_bpm = round(sig.resting_hr - sig.rhr_baseline_mean, 1)

    sig.acwr = acwr(daily_trimp_map(conn, day, days=35), day)

    subj = conn.execute("SELECT * FROM subjective WHERE date = ?", (d,)).fetchone()
    if subj is not None:
        sig.subjective = {
            "sleep_feel": subj["sleep_feel"],
            "stress": subj["stress"],
            "soreness": subj["soreness"],
            "motivation": subj["motivation"],
        }
    return sig


def _score(sig: Signals) -> int:
    """0–100-kompositt. Grov, men deterministisk og monoton i hver komponent:
    base 50, HRV ±30 (z klippet ±2.5), søvnscore ±9, Body Battery ±5,
    subjektiv stølhet/stress trekker ned."""
    score = 50.0
    if sig.hrv_z is not None:
        score += max(-2.5, min(2.5, sig.hrv_z)) * 12.0
    if sig.sleep_score is not None:
        score += (sig.sleep_score - 70) * 0.3
    if sig.body_battery_high is not None:
        score += (sig.body_battery_high - 70) * 0.15
    if sig.subjective:
        soreness = sig.subjective.get("soreness")
        stress = sig.subjective.get("stress")
        if soreness:
            score -= (soreness - 2) * 5.0
        if stress:
            score -= (stress - 3) * 3.0
    return int(max(0.0, min(100.0, round(score))))


def evaluate(sig: Signals, r_cfg: ReadinessCfg, l_cfg: LoadCfg) -> Decision:
    if sig.hrv_baseline_n < r_cfg.min_baseline_days:
        return Decision(
            status="calibrating",
            recommendation="calibrating",
            rules_fired=["calibrating_gate"],
            score=None,
        )

    fired: list[str] = []
    score = _score(sig)
    soreness = (sig.subjective or {}).get("soreness")

    if sig.acwr is not None and sig.acwr > l_cfg.acwr_ceiling:
        return Decision("ok", "forced_easy_week", ["acwr_ceiling"], score)

    hrv_red = sig.hrv_z is not None and sig.hrv_z < r_cfg.hrv_z_red
    short_sleep = sig.short_nights_last2 >= r_cfg.short_sleep_nights
    if hrv_red or short_sleep:
        if hrv_red:
            fired.append("hrv_red")
        if short_sleep:
            fired.append("short_sleep")
        return Decision("ok", "swap_to_easy", fired, score)

    if sig.hrv_z is not None and sig.hrv_z < r_cfg.hrv_z_yellow:
        return Decision("ok", "reduce_intensity", ["hrv_yellow"], score)

    if (
        sig.hrv_z is not None
        and sig.hrv_z > r_cfg.hrv_z_green_high
        and sig.acwr is not None
        and sig.acwr < l_cfg.acwr_floor
    ):
        if soreness is not None and soreness >= 4:
            return Decision("ok", "run_plan", ["hrv_green_add_load", "soreness_downgrade"], score)
        return Decision("ok", "add_load", ["hrv_green_add_load"], score)

    return Decision("ok", "run_plan", ["run_plan"], score)
