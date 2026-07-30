# Workflows

One directory per channel. Workflows are **channel-scoped at creation time** (the
channel is not part of the YAML), and the engine has **no "run agent" action** —
every hand-off is a `send_message` that @-mentions the responsible agent, whose
mention-trigger picks it up.

| Channel | File | Trigger |
|---|---|---|
| `#hushold` | `hushold/ukeplan-vask.yaml` | Sun 16:00 UTC |
| `#handleliste` | `handleliste/reaksjon-legg-til.yaml` | 🛒 reaction |
| `#handleliste` | `handleliste/fredagsdigest.yaml` | Fri 13:30 UTC |
| `#okonomi` | `okonomi/ukesrapport.yaml` | Mon 05:00 UTC |
| `#okonomi` | `okonomi/manedsrapport-godkjenning.yaml` | monthly, 1st 06:00 UTC (approval gate) |
| `#automasjon-backlog` | `automasjon-backlog/intake.yaml` | message contains `!auto` |
| `#automasjon-backlog` | `automasjon-backlog/ukentlig-rangering.yaml` | Sun 15:00 UTC |

## Validate offline

```bash
cargo run --manifest-path life-ops/verify/Cargo.toml
```

This parses every YAML here with the real `buzz-workflow` schema code (same
validation the relay runs), including cron expressions.

## Install

Requires `BUZZ_RELAY_URL` + `BUZZ_PRIVATE_KEY` (owner key) in the environment and
the **Workflows** preview feature enabled in the desktop app to see/manage them.

```bash
# find channel UUIDs
buzz --format compact channels list

# install (repeat per file, against its channel)
buzz workflows create --channel <CHANNEL_UUID> --yaml "$(cat life-ops/workflows/hushold/ukeplan-vask.yaml)"

# safe manual test of schedule-type workflows
buzz workflows trigger --workflow <WORKFLOW_UUID>

# after editing a file
buzz workflows update --channel <CHANNEL_UUID> --workflow <WORKFLOW_UUID> --yaml "$(cat <file>)"
```

## Operational notes

- **Cron is UTC.** Every scheduled file has a header comment with its Oslo local
  time; re-issue `workflows update` after DST shifts if the hour matters. Named
  weekdays (`SUN`, `MON`, `FRI`) are deliberate.
- **Reaction semantics:** in reaction-triggered runs, `{{trigger.text}}` is the
  emoji itself; the reacted message id is `{{trigger.message_id}}`. Verify the 🛒
  literal against the relay debug log on first use ("Reaction emoji mismatch").
- **Loop guards:** never emit a workflow's own trigger token in its output (see
  `intake.yaml`), and don't add reaction-workflows that react with their own
  trigger emoji.
- **Approvals:** `request_approval` suspends the run; approve with the desktop UI
  or `buzz workflows approve --token <UUID>`; branch on
  `steps_<id>_output_approved` (`== true` / `== false`).
- **No run history via CLI** on this build (`workflows runs` returns `[]`) — every
  scheduled workflow therefore posts a visible channel message as its own heartbeat.
- Agents must be running with `BUZZ_ACP_RESPOND_TO=anyone` (closed relay) or the
  workflow-posted mentions are silently dropped by the owner-only default gate.
