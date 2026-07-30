# Life-Ops — a personal agent team for Buzz

Self-contained assets for running a **personal life-operations agent team** on a Buzz
relay: four Norwegian-speaking agents (orchestrator, finance, household, shopping),
seven channel workflows, a ranked automation backlog, a VPS runbook, and a reusable
skill that teaches agents (and Claude Code) how to design Buzz teams well.

Nothing in this directory touches upstream Buzz code. The only files outside it are
byte-identical mirrors of the skill under `.agents/skills/`, `.claude/skills/`,
`.codex/skills/`, and `.goose/skills/` (the repo's normal skill locations).

## Map

| Path | What it is |
|---|---|
| [`PLAN.md`](PLAN.md) | The automation plan: use cases, agent roster, channel design, ranked backlog (rangeringsliste), Buzz-vs-Claude-Code decision framework, rollout waves, risks |
| [`pack/`](pack/) | Persona pack **Life Ops** (`com.robinshood.life-ops`) — import via desktop *My Teams → Import* or deploy per persona on the VPS |
| [`workflows/`](workflows/) | Seven workflow YAMLs, one directory per channel, plus install instructions |
| [`runbook/`](runbook/) | `VPS-SETUP.md` end-to-end setup (relay → agents → Era Context → backups), systemd templates, helper scripts |
| [`verify/`](verify/) | Offline validator: parses every workflow YAML with the real `buzz-workflow` schema code |

## Quickstart

```bash
# 1. Validate everything offline (no relay needed)
cargo build --release -p buzz-cli
./target/release/buzz pack validate life-ops/pack
cargo run --manifest-path life-ops/verify/Cargo.toml

# 2. Try it locally first (desktop app + `just relay`)
#    My Teams → Import → select a zip of life-ops/pack, or import personas one by one.
#    Enable Settings → preview features → Workflows.
#    Install one workflow:  buzz workflows create --channel <uuid> --yaml "$(cat life-ops/workflows/hushold/ukeplan-vask.yaml)"

# 3. Go always-on
#    Follow runbook/VPS-SETUP.md (relay via deploy/compose, one buzz-acp service per agent).
```

Read `PLAN.md` first — it explains the order things are meant to be rolled out in
(Wave 0 smoke test → Wave 1 household/shopping/backlog → Wave 2 finance → Wave 3
expansion through the weekly ranking ritual).
