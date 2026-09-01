"""Innstillinger: stier fra miljøet, terskler fra config.toml.

Terskler har innebygde defaults identiske med den committede config.toml,
slik at alt virker selv uten config-fil (f.eks. i tester).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class ReadinessCfg:
    min_baseline_days: int = 28
    baseline_window_days: int = 60
    hrv_z_red: float = -1.5
    hrv_z_yellow: float = -0.5
    hrv_z_green_high: float = 1.0
    short_sleep_hours: float = 6.0
    short_sleep_nights: int = 2
    rhr_dev_flag_bpm: float = 5.0


@dataclass(frozen=True)
class LoadCfg:
    acwr_ceiling: float = 1.5
    acwr_floor: float = 0.8
    monotony_flag: float = 2.0
    throttle_seconds: float = 1.5


@dataclass(frozen=True)
class E1rmCfg:
    epley_max_reps: int = 12
    trend_min_points: int = 3


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    readiness: ReadinessCfg = field(default_factory=ReadinessCfg)
    load: LoadCfg = field(default_factory=LoadCfg)
    e1rm: E1rmCfg = field(default_factory=E1rmCfg)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "garmin.db"

    @property
    def tokens_dir(self) -> Path:
        return self.data_dir / "tokens"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"


def _find_config() -> Path | None:
    env = os.environ.get("GARMIN_PT_CONFIG")
    if env:
        return Path(env).expanduser()
    candidates = (
        Path.cwd() / "config.toml",
        # repo-checkout: garmin-pt/config.toml ved siden av src/
        Path(__file__).resolve().parents[2] / "config.toml",
    )
    for cand in candidates:
        if cand.exists():
            return cand
    return None


def load_settings(config_path: Path | None = None, data_dir: Path | None = None) -> Settings:
    load_dotenv()
    if data_dir is None:
        data_dir = Path(os.environ.get("GARMIN_PT_DATA_DIR", "~/.garmin-pt")).expanduser()
    raw: dict = {}
    path = config_path or _find_config()
    if path is not None and path.exists():
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return Settings(
        data_dir=data_dir,
        readiness=ReadinessCfg(**raw.get("readiness", {})),
        load=LoadCfg(**raw.get("load", {})),
        e1rm=E1rmCfg(**raw.get("e1rm", {})),
    )
