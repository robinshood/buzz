# Life Ops persona pack

Four Norwegian-speaking agents for personal life operations. See
[`../PLAN.md`](../PLAN.md) for the roster, channels, and rollout order.

| Persona | Display | Role | Model (placeholder) |
|---|---|---|---|
| `los` | Los | Orchestrator / ranks the automation backlog | `anthropic:claude-opus-5` |
| `ore` | Øre | Finance via Era Context MCP (read-free, write-gated) | `anthropic:claude-opus-5`, temp 0.3 |
| `vaskebjorn` | Vaskebjørn | Household weekly plan | pack default (`anthropic:claude-sonnet-5`) |
| `kurv` | Kurv | Shopping list canvas | pack default |

**Model ids are placeholders** — set them to whatever your subscription offers
(pack `defaults.model` + per-persona `model:`), and mirror the choice in the
per-service `BUZZ_ACP_MODEL` on the VPS (operator env wins over pack values).

## Validate

```bash
cargo build --release -p buzz-cli
./target/release/buzz pack validate life-ops/pack
./target/release/buzz pack inspect  life-ops/pack   # shows effective per-persona config
```

## Install

- **Desktop (local try-out):** zip this directory (so `.plugin/plugin.json` is at the
  zip root) and import via **My Teams → Import** — the pack name becomes the team,
  each persona a member. Or import `agents/*.persona.md` one by one via
  **My Agents → Import**.
- **VPS (always-on):** this build of `buzz-acp` has no pack auto-load; run one
  `buzz-acp` service per persona with the prompt body rendered to a file
  (`../runbook/bin/render-prompts.sh`) and behavior mapped to `BUZZ_ACP_*` env vars.
  Full walkthrough: [`../runbook/VPS-SETUP.md`](../runbook/VPS-SETUP.md).

## Notes

- `ore`'s MCP entry points at `/srv/lifeops/bin/era-mcp.sh` — a wrapper script
  (no secrets in the pack; `${VAR}` interpolation is **not** implemented in this
  build, so literal env references would not resolve).
- The pack ships the `buzz-team-design` skill under `skills/`; the same skill is
  mirrored at the repo root skill directories for Claude Code and buzz-acp discovery.
- Persona frontmatter is parsed with `deny_unknown_fields` — a typo in a key is a
  hard error, which `buzz pack validate` will surface.
