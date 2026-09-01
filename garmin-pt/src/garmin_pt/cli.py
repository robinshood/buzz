"""Agent- og cron-vennlig CLI: auth | ingest | status | subjective |
push-workout | reparse.

Exit-koder: 0 = ok (også rate_limited — neste kjøring resumer fra watermark),
3 = auth-feil (krever 'garmin-pt auth'), 4 = annen feil.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date as Date
from datetime import timedelta
from pathlib import Path

from . import db
from .config import load_settings
from .garmin import auth as g_auth
from .garmin.client import AuthError
from .ingest import activities as t_act
from .ingest import daily as t_daily
from .ingest import strength as t_strength
from .ingest.runner import IngestRunner, default_range, get_watermark


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def cmd_auth(args) -> int:
    settings = load_settings()
    if args.check:
        _print(g_auth.token_status(settings))
        return 0
    try:
        g_auth.login(settings, interactive=True)
    except AuthError as e:
        print(f"Innlogging feilet: {e}", file=sys.stderr)
        return 3
    print(f"Innlogget OK. Tokens lagret i {settings.tokens_dir}")
    return 0


def cmd_ingest(args) -> int:
    settings = load_settings()
    conn = db.connect(settings.db_path)
    today = Date.today()
    if args.backfill:
        date_from, date_to = today - timedelta(days=args.backfill), today
        mode = "backfill"
    elif args.date_from:
        date_from = Date.fromisoformat(args.date_from)
        date_to = Date.fromisoformat(args.date_to) if args.date_to else today
        mode = "backfill"
    else:
        date_from, date_to = default_range(conn, today)
        mode = "daily"
    try:
        client = g_auth.login(settings, interactive=sys.stdin.isatty())
    except AuthError as e:
        print(f"Auth-feil: {e}", file=sys.stderr)
        return 3
    runner = IngestRunner(client, conn, settings, store_raw=not args.no_raw)
    result = runner.run(date_from, date_to, mode=mode)
    _print(
        {
            "status": result.status,
            "range": [date_from.isoformat(), date_to.isoformat()],
            "days_done": result.days_done,
            "api_calls": result.api_calls,
            "error": result.error,
        }
    )
    if result.status == "auth_error":
        return 3
    if result.status == "error":
        return 4
    return 0  # ok og rate_limited: watermark står riktig, neste kjøring resumer


def cmd_status(args) -> int:
    settings = load_settings()
    out: dict = {"data_dir": str(settings.data_dir), "tokens": g_auth.token_status(settings)}
    if not settings.db_path.exists():
        out["db"] = "finnes ikke — aldri synket (kjør 'garmin-pt ingest --backfill 365')"
        _print(out)
        return 0
    conn = db.connect(settings.db_path, read_only=True)
    try:
        out["watermarks"] = {d: get_watermark(conn, d) for d in ("daily", "activities", "metrics")}
        out["rows"] = {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: S608
            for t in (
                "daily",
                "activities",
                "strength_sets",
                "metrics",
                "plan",
                "subjective",
                "raw_payloads",
            )
        }
        runs = conn.execute(
            "SELECT started_at, finished_at, mode, status, days_done, api_calls, error "
            "FROM sync_runs ORDER BY id DESC LIMIT 5"
        ).fetchall()
        out["last_runs"] = [dict(r) for r in runs]
        bad = [r for r in out["last_runs"] if r["status"] in ("auth_error", "error")]
        if bad:
            out["attention"] = f"SISTE KJØRINGER FEILET ({bad[0]['status']}): {bad[0]['error']}"
    finally:
        conn.close()
    _print(out)
    return 0


def _ask_int(prompt: str) -> int:
    while True:
        raw = input(f"{prompt} (1-5): ").strip()
        if raw.isdigit() and 1 <= int(raw) <= 5:
            return int(raw)
        print("Skriv et heltall 1-5.")


def cmd_subjective(args) -> int:
    from .mcp_server import log_subjective

    values = {
        "sleep_feel": args.sleep_feel or _ask_int("Søvnfølelse"),
        "stress": args.stress or _ask_int("Stress"),
        "soreness": args.soreness or _ask_int("Stølhet"),
        "motivation": args.motivation or _ask_int("Motivasjon"),
    }
    result = log_subjective(
        **values,
        date=args.date,
        soreness_location=args.location,
        note=args.note,
    )
    _print(result)
    return 0 if "error" not in result else 4


def cmd_push_workout(args) -> int:
    from .mcp_server import push_workout_to_garmin

    spec = json.loads(Path(args.file).read_text(encoding="utf-8"))
    result = push_workout_to_garmin(spec, schedule_date=args.date)
    _print(result)
    if result.get("error") == "auth_expired":
        return 3
    return 0 if "error" not in result else 4


def cmd_reparse(args) -> int:
    """Re-kjør transforms fra raw_payloads etter en parser-fiks — uten nettverk."""
    settings = load_settings()
    conn = db.connect(settings.db_path)
    counts = {"daily": 0, "activities": 0, "strength": 0, "dumped": 0}
    try:
        if args.dump_fixtures:
            outdir = Path(args.dump_fixtures)
            outdir.mkdir(parents=True, exist_ok=True)
            for row in conn.execute("SELECT * FROM raw_payloads"):
                name = f"{row['domain']}_{row['endpoint'].replace(':', '_')}_{row['date']}.json"
                (outdir / name).write_text(row["payload"], encoding="utf-8")
                counts["dumped"] += 1
            _print(counts)
            return 0

        by_date: dict[str, dict] = {}
        for row in conn.execute("SELECT * FROM raw_payloads WHERE domain = 'daily'"):
            by_date.setdefault(row["date"], {})[row["endpoint"]] = json.loads(row["payload"])
        for d, payloads in by_date.items():
            record = t_daily.daily_row(
                d,
                hrv=payloads.get("hrv_day"),
                sleep=payloads.get("sleep_day"),
                rhr=payloads.get("rhr_day"),
                summary=payloads.get("user_summary"),
                weigh_ins=payloads.get("weigh_ins"),
            )
            db.upsert(conn, "daily", record, ["date"], touch="updated_at")
            counts["daily"] += 1

        for row in conn.execute("SELECT * FROM raw_payloads WHERE domain = 'activities'"):
            record = t_act.activity_row(json.loads(row["payload"]))
            if record:
                db.upsert(conn, "activities", record, ["activity_id"], touch="updated_at")
                counts["activities"] += 1

        for row in conn.execute("SELECT * FROM raw_payloads WHERE domain = 'strength'"):
            activity_id = int(row["endpoint"].split(":", 1)[1])
            for record in t_strength.strength_rows(
                activity_id,
                row["date"],
                json.loads(row["payload"]),
                epley_max_reps=settings.e1rm.epley_max_reps,
            ):
                db.upsert(
                    conn,
                    "strength_sets",
                    record,
                    ["activity_id", "set_index"],
                    conflict_where="source = 'garmin'",
                    touch="updated_at",
                )
                counts["strength"] += 1
        conn.commit()
    finally:
        conn.close()
    _print(counts)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="garmin-pt", description="PT-datalag over Garmin Connect")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_auth = sub.add_parser("auth", help="logg inn (interaktiv MFA om nødvendig)")
    p_auth.add_argument("--check", action="store_true", help="bare sjekk token-filer")
    p_auth.set_defaults(fn=cmd_auth)

    p_ing = sub.add_parser("ingest", help="hent data til SQLite")
    p_ing.add_argument("--backfill", type=int, metavar="DAGER")
    p_ing.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD")
    p_ing.add_argument("--to", dest="date_to", metavar="YYYY-MM-DD")
    p_ing.add_argument("--no-raw", action="store_true", help="ikke lagre rå-payloads")
    p_ing.set_defaults(fn=cmd_ingest)

    p_status = sub.add_parser("status", help="watermarks, siste kjøringer, radtall")
    p_status.set_defaults(fn=cmd_status)

    p_subj = sub.add_parser("subjective", help="dagens 15-sekunders selvrapport")
    p_subj.add_argument("--date", default="today")
    p_subj.add_argument("--sleep-feel", type=int, dest="sleep_feel")
    p_subj.add_argument("--stress", type=int)
    p_subj.add_argument("--soreness", type=int)
    p_subj.add_argument("--motivation", type=int)
    p_subj.add_argument("--location", help="hvor stølheten sitter")
    p_subj.add_argument("--note")
    p_subj.set_defaults(fn=cmd_subjective)

    p_push = sub.add_parser("push-workout", help="push økt-spec (JSON-fil) til Garmin")
    p_push.add_argument("file")
    p_push.add_argument("--date", help="kalenderdato YYYY-MM-DD")
    p_push.set_defaults(fn=cmd_push_workout)

    p_rep = sub.add_parser("reparse", help="re-kjør transforms fra raw_payloads (ingen nettverk)")
    p_rep.add_argument(
        "--dump-fixtures", metavar="DIR", help="eksporter rå-payloads som JSON-filer"
    )
    p_rep.set_defaults(fn=cmd_reparse)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
