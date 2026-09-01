"""SQLite-skjema. Én streng per skjemaversjon; indeks+1 = PRAGMA user_version.

Nye endringer = nytt element i MIGRATIONS — aldri rediger et eksisterende.
"""

MIGRATIONS: list[str] = [
    # v1
    """
    CREATE TABLE daily (
      date                TEXT PRIMARY KEY,
      hrv_last_night_avg  REAL,
      hrv_status          TEXT,
      resting_hr          INTEGER,
      sleep_score         INTEGER,
      sleep_duration_min  REAL,
      sleep_deep_min      REAL,
      sleep_rem_min       REAL,
      sleep_light_min     REAL,
      sleep_awake_min     REAL,
      body_battery_high   INTEGER,
      body_battery_low    INTEGER,
      stress_avg          INTEGER,
      steps               INTEGER,
      weight_kg           REAL,
      updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE activities (
      activity_id     INTEGER PRIMARY KEY,
      date            TEXT NOT NULL,
      start_time      TEXT,
      activity_type   TEXT NOT NULL,
      name            TEXT,
      duration_s      REAL,
      distance_m      REAL,
      avg_hr          INTEGER,
      max_hr          INTEGER,
      hr_zone_1_s     REAL,
      hr_zone_2_s     REAL,
      hr_zone_3_s     REAL,
      hr_zone_4_s     REAL,
      hr_zone_5_s     REAL,
      aerobic_te      REAL,
      anaerobic_te    REAL,
      calories        REAL,
      garmin_load     REAL,
      trimp           REAL,
      updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_activities_date ON activities(date);
    CREATE INDEX idx_activities_type_date ON activities(activity_type, date);

    CREATE TABLE strength_sets (
      id           INTEGER PRIMARY KEY,
      activity_id  INTEGER REFERENCES activities(activity_id) ON DELETE CASCADE,
      date         TEXT NOT NULL,
      exercise     TEXT NOT NULL,
      muscle_group TEXT,
      set_index    INTEGER NOT NULL,
      reps         INTEGER,
      weight_kg    REAL,
      duration_s   REAL,
      rir          REAL,
      rpe          REAL,
      e1rm         REAL,
      source       TEXT NOT NULL DEFAULT 'garmin',
      superseded   INTEGER NOT NULL DEFAULT 0,
      updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE UNIQUE INDEX ux_strength_garmin
      ON strength_sets(activity_id, set_index) WHERE source = 'garmin';
    CREATE INDEX idx_strength_exercise_date ON strength_sets(exercise, date);
    CREATE INDEX idx_strength_muscle_date ON strength_sets(muscle_group, date);

    CREATE TABLE metrics (
      week_start      TEXT PRIMARY KEY,
      vo2max          REAL,
      training_status TEXT,
      threshold_hr    INTEGER,
      resting_hr_avg  REAL,
      weight_avg_kg   REAL,
      weekly_trimp    REAL,
      acwr            REAL,
      monotony        REAL,
      updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE plan (
      id                    INTEGER PRIMARY KEY,
      date                  TEXT NOT NULL,
      planned_type          TEXT NOT NULL,
      planned_detail        TEXT,
      garmin_workout_id     TEXT,
      executed_activity_id  INTEGER REFERENCES activities(activity_id),
      executed              INTEGER,
      deviation             TEXT,
      pt_reasoning          TEXT,
      created_at            TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_plan_date ON plan(date);

    CREATE TABLE subjective (
      date              TEXT PRIMARY KEY,
      sleep_feel        INTEGER CHECK (sleep_feel BETWEEN 1 AND 5),
      stress            INTEGER CHECK (stress BETWEEN 1 AND 5),
      soreness          INTEGER CHECK (soreness BETWEEN 1 AND 5),
      soreness_location TEXT,
      motivation        INTEGER CHECK (motivation BETWEEN 1 AND 5),
      note              TEXT,
      updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE sync_watermarks (
      domain           TEXT PRIMARY KEY,
      last_synced_date TEXT NOT NULL,
      updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE sync_runs (
      id          INTEGER PRIMARY KEY,
      started_at  TEXT NOT NULL DEFAULT (datetime('now')),
      finished_at TEXT,
      mode        TEXT NOT NULL,
      date_from   TEXT,
      date_to     TEXT,
      status      TEXT NOT NULL DEFAULT 'running',
      days_done   INTEGER NOT NULL DEFAULT 0,
      api_calls   INTEGER NOT NULL DEFAULT 0,
      error       TEXT
    );

    CREATE TABLE raw_payloads (
      domain     TEXT NOT NULL,
      date       TEXT NOT NULL,
      endpoint   TEXT NOT NULL,
      payload    TEXT NOT NULL,
      fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
      PRIMARY KEY (domain, date, endpoint)
    );
    """
]
