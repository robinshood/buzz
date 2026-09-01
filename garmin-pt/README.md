# Garmin-PT — datalag for en dynamisk personlig trener

Daglig ingest av Garmin-data til lokal SQLite + en kuratert MCP-server med 8
verktøy som svarer med **konklusjoner, ikke datadumper**. PT-en (Claude i
Cowork/Claude Code) leser alltid fra ditt eget lager — aldri live mot Garmin —
fordi Garmins SSO er aggressivt rate-limitet og auth har brukket flere ganger.

```
Garmin Fenix ──sync──► Garmin Connect
                          │  garmin-pt ingest   (1×/døgn, cron 05:30)
                          ▼
                  ~/.garmin-pt/garmin.db        ← sannheten din
                          │
                          ▼
                  garmin-pt-mcp  (8 verktøy)  ──► Claude (Cowork / Claude Code)
```

Eneste verktøy som rører nettet er `push_workout_to_garmin` (legger økter i
Garmin-kalenderen — skriv er sjeldne, så rate limiting biter ikke der).

## Oppsett (lokalt, én gang)

Krav: [uv](https://docs.astral.sh/uv/) (håndterer Python 3.12 selv) og en
Garmin-konto. Aktiver gjerne MFA med autentiseringsapp i Garmin-kontoen og
ta vare på TOTP-nøkkelen (base32-strengen) når du setter den opp.

```bash
cd garmin-pt
uv sync --extra totp        # --extra totp gir automatisk MFA via GARMIN_TOTP_SECRET
cp .env.example .env        # fyll inn GARMIN_EMAIL / GARMIN_PASSWORD (+ evt. TOTP-secret)
```

`.env`, `*.db` og `tokens/` er gitignored — de skal aldri inn i git. Alle
runtime-data ligger utenfor repoet i `~/.garmin-pt/` (overstyr med
`GARMIN_PT_DATA_DIR`).

## Første innlogging og backfill

```bash
uv run garmin-pt auth                    # interaktiv MFA om nødvendig; tokens → ~/.garmin-pt/tokens/
uv run garmin-pt ingest --backfill 365   # ~2500 kall à 1,5 s throttle ≈ 65 min
uv run garmin-pt status                  # watermarks, siste kjøringer, radtall
```

Backfill er **avbrytbar og resumbar**: alle skriv er upserts og watermark
flyttes bare etter helt ferdige dager. Får du 429 (`status: rate_limited`),
er det ikke en feil — kjør igjen senere, den fortsetter der den slapp.

**Verifiser dataene** før du stoler på dem: sammenlign 2–3 dager (HRV, søvn,
hvilepuls) og én styrkeøkt (øvelser/sett/reps) mot Garmin Connect-appen.
Feltstiene i parserne er skrevet mot dokumenterte API-former, ikke live-data:

```bash
uv run garmin-pt reparse --dump-fixtures /tmp/garmin-fixtures   # ekte payloads fra rå-cachen
# stemmer noe ikke: fiks transformen, og re-bygg radene UTEN nye Garmin-kall:
uv run garmin-pt reparse
```

Bytt gjerne de provisoriske filene i `tests/fixtures/` med (anonymiserte)
ekte payloads fra dumpen.

## Daglig ingest (cron 05:30)

```bash
crontab -e
# macOS/Linux — juster stier (finn uv-stien med: which uv)
30 5 * * * /Users/robin/.local/bin/uv --directory /sti/til/garmin-pt run garmin-pt ingest >> "$HOME/.garmin-pt/logs/ingest.log" 2>&1
```

Lag loggmappen først: `mkdir -p ~/.garmin-pt/logs`. På macOS er launchd mer
robust (kjører når maskinen våkner); legg tilsvarende kommando i en plist
under `~/Library/LaunchAgents/` med `StartCalendarInterval` 05:30 hvis cron
viser seg upålitelig.

Tokens auto-refreshes ved hver kjøring. Utløper hele sesjonen (uker uten
kjøring, eller Garmin brekker auth igjen) får kjøringen `status: auth_error`
— `garmin-pt status` roper om det i `attention`-feltet. Med
`GARMIN_TOTP_SECRET` satt re-autentiserer ingest uten deg; uten må du kjøre
`uv run garmin-pt auth` én gang.

## Koble PT-en til dataene (MCP)

Claude Code:

```bash
claude mcp add garmin-pt -- uv --directory /sti/til/garmin-pt run garmin-pt-mcp
```

Cowork / Claude Desktop (`claude_desktop_config.json` → `mcpServers`):

```json
{
  "garmin-pt": {
    "command": "uv",
    "args": ["--directory", "/sti/til/garmin-pt", "run", "garmin-pt-mcp"]
  }
}
```

### De 8 verktøyene

| Verktøy | Svarer med |
|---|---|
| `get_readiness(date)` | HRV z-score mot egen 60d-baseline, søvn, hvilepuls, ACWR, subjektiv → én anbefaling (`run_plan` / `reduce_intensity` / `swap_to_easy` / `add_load` / `forced_easy_week`) |
| `get_training_load(weeks)` | ukesvolum, TRIMP, tid per HR-sone, akutt:kronisk, monotoni |
| `get_strength_progression(muscle_group, exercise, weeks)` | e1RM-trend (Epley) og volumtrend per øvelse, med andel komplette sett |
| `get_recent_sessions(n)` | siste økter, planlagt-vs-utført-avvik |
| `get_fitness_markers()` | VO2max-, terskel-, hvilepuls- og vekttrend |
| `log_subjective(...)` | dagens 15-sekunders selvrapport (1–5) |
| `log_strength_session(...)` | manuell korrigering av sett/reps/vekt (garmin-rader markeres `superseded`, slettes aldri) |
| `push_workout_to_garmin(workout, schedule_date)` | bygger strukturert økt og legger den i Garmin-kalenderen |

Beslutningsterskler (HRV-soner, ACWR-tak, Epley-parametre) ligger i
`config.toml` — endre der, ikke i koden.

## Kalibrering — viktig

**Readiness svarer `calibrating` til baseline har ≥ 28 netter HRV**, og
rådene er først fullt til å stole på etter ~4 uker med data (backfill på 12
måneder løser dette umiddelbart). Verktøyene oppgir alltid datagrunnlaget
sitt («45 netter HRV i 60d-baseline») — tynn basis skal synes.

## Kjente forbehold

- **`push_workout_to_garmin` er minst verifisert**: Garmins id-koder for
  sport/steg i `workouts.py` er hentet fra tredjepartsprosjekter (medium
  konfidens). Verifiser første live-push mot kalenderen i appen; feiler den,
  er det tabellene øverst i `workouts.py` som skal justeres.
- **Vekt-enhet fra klokka**: Garmin oppgir gram; verdier < 400 tolkes som
  allerede-kg (enhetsvern). Ser vektene rare ut etter første ingest — sjekk
  `_weight_kg` i `src/garmin_pt/ingest/strength.py` og kjør `reparse`.
- **Styrkedata fra klokka er upresise**: reps kan være gjettet og vekt
  mangler ofte. e1RM beregnes bare på komplette sett; bruk
  `log_strength_session` for å korrigere nøkkeløkter.

## Agentene: Coach + Forsker på Buzz (fase 4–6)

PT-agenten («Coach», Sonnet 5) og research-agenten («Forsker», Opus 5) er
levert som en Buzz persona-pakke i [`pack/`](pack/) med tilhørende
cron-workflows i [`workflows/`](workflows/) (mandagsplan, daglig
morgensjekk, søndagsoppsummering). Oppsett — nøkler, #trening-kanal,
launchd-kjøring av buzz-acp med `claude-agent-acp`-runtimen, og
workflow-registrering — står i [`pack/README.md`](pack/README.md).

## Utvikling

```bash
uv run pytest          # 85 tester, alle offline (nettverk er hardt blokkert i testene)
uv run ruff check src tests && uv run ruff format --check src tests
```

All Garmin-API-kontakt går gjennom `src/garmin_pt/garmin/client.py` — driver
API-et, er det dén filen (og bare den) som fikses; transforms re-kjøres
etterpå med `reparse`.

---

Dette er et personlig treningsverktøy, ikke medisinsk utstyr. Brystsmerter,
uvanlig tungpust eller vedvarende unormale pulsverdier hører hjemme hos lege,
ikke i en beslutningsregel.
