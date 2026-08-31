"""SQLite-tilkobling, migrering via PRAGMA user_version, og upsert-helper."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path

from .schema import MIGRATIONS


def connect(db_path: Path | str, *, read_only: bool = False) -> sqlite3.Connection:
    """Åpne databasen. Skrivbar tilkobling migrerer til siste skjemaversjon;
    read-only (brukes av MCP-leseverktøyene) kan aldri endre noe."""
    if read_only:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for target, script in enumerate(MIGRATIONS[version:], start=version + 1):
        conn.executescript(script)
        conn.execute(f"PRAGMA user_version = {target}")
        conn.commit()


def upsert(
    conn: sqlite3.Connection,
    table: str,
    row: dict,
    key_cols: Sequence[str],
    *,
    conflict_where: str | None = None,
    touch: str | None = None,
) -> None:
    """INSERT ... ON CONFLICT DO UPDATE for alle ingest-skriv — idempotent.

    conflict_where trengs når konfliktmålet er en partiell unik indeks
    (strength_sets). touch settes til en updated_at-kolonne som skal
    fornyes ved oppdatering.
    """
    cols = list(row)
    placeholders = ", ".join(f":{c}" for c in cols)
    updates = [f"{c} = excluded.{c}" for c in cols if c not in key_cols]
    if touch:
        updates.append(f"{touch} = datetime('now')")
    conflict = f"({', '.join(key_cols)})"
    if conflict_where:
        conflict += f" WHERE {conflict_where}"
    sql = (
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT{conflict} DO UPDATE SET {', '.join(updates)}"
    )
    conn.execute(sql, row)
