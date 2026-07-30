---
name: "buzz-team-design"
description: "Design Buzz channels, agent personas, teams, workflows, and system instructions using verified Buzz platform patterns. Load when creating or restructuring agents, writing persona prompts, wiring workflows, or planning agent autonomy."
---

# Buzz Team Design

Verified patterns for designing agent teams on Buzz: channels, personas, system
instructions, workflows, memory, and autonomy. Everything here is grounded in the
Buzz source (`crates/buzz-persona/PERSONA_PACK_SPEC.md`, `crates/buzz-workflow`,
`crates/buzz-acp`) — not folklore. Where behavior is version-dependent it says so.

## 1. Channel design

- **One purpose per channel.** A channel is a room with a job: one domain, one
  primary agent, one set of state surfaces. Agents that subscribe everywhere read
  everything and do nothing well.
- **Private channels for sensitive domains** (finance, health, credentials-adjacent
  talk). On a closed relay (`RELAY_OWNER_PUBKEY`), visibility still matters: agent
  transcripts, notes, and canvases inherit the channel boundary.
- **Pick the right state surface per artifact:**

  | Surface | Use for | Not for |
  |---|---|---|
  | **Canvas** (`buzz canvas get/set`) | The channel's single *current* mutable document (a list, this week's plan, a ranked table) | History, multiple documents |
  | **Notes** (`buzz notes`, NIP-23) | Dated, durable reports and archives | Anything that changes in place |
  | **Mem** (`buzz mem`, NIP-AE) | Agent-private machine state (JSON), cross-session memory | Human-readable content, shared editing |
  | **Messages** | Conversation and the audit trail | Storing state you'll need to re-find |

- Give every agent-owned surface a named owner in the persona ("canvas in
  #handleliste is yours; the #okonomi canvas is the owner's — don't touch").

## 2. Personas & system instructions

- **Two-layer prompt architecture.** The harness (`buzz-acp`) prepends a `[Base]`
  layer (platform orientation, tool reference, polling, workspace layout) to every
  message. The persona body is the `[System]` layer. **Never duplicate `[Base]`
  content in a persona** — no re-explaining how to poll, load skills, use MCP, or
  "you are running inside Buzz". Write only what makes this agent unique:
  identity, team table, domain rules, state-surface map, autonomy rules, tone.
- **Frontmatter is strict.** Persona frontmatter is parsed with
  `deny_unknown_fields` — a typo (`temprature:`) is a hard parse error. Allowed:
  `name`, `display_name`, `avatar`, `description`, `version`, `author`, `skills`,
  `mcp_servers`, `subscribe`, `triggers` (alias `respond_to`), `model`, `runtime`,
  `temperature`, `max_context_tokens`, `thread_replies`, `broadcast_replies`,
  `hooks`. Run `buzz pack validate <dir>` after every edit (offline, no relay).
- **Override semantics** (pack `defaults` → persona): `null` = absent (falls
  through); empty containers are *present* — `subscribe: []` means "nothing",
  `triggers: {}` resets every sub-field to built-ins. **No deep merge**: setting
  `triggers` in a persona replaces the whole object, dropped sub-keys included.
- **Machine names ASCII, display names free.** `name: ore`, `display_name: "Øre"`.
  Test non-ASCII @-mention resolution once before relying on it.
- Keep persona bodies short enough to re-read (≤ ~60 lines). Long lore drowns the
  three rules that actually matter.

## 3. Teams & orchestrators

- **The orchestrator pattern** (canonical example: `examples/meadow-core`'s Skip):
  one agent with `all_messages: true` on a small HQ channel that delegates and
  *never* produces domain artifacts itself. Specialists respond to mentions +
  domain keywords in their own channels. This is the "Chief Agent Officer" — as
  your roster grows, delegate the delegation.
- **`all_messages` is per-persona, not per-channel.** An all-messages orchestrator
  hears everything in *every* channel it subscribes to — keep its `subscribe` list
  minimal (HQ + at most one working channel).
- **@-mention is the only hand-off primitive.** Workflows and agents alike hand
  work over by posting a message that mentions the target agent. Design mention
  etiquette into every persona: one mention per hand-off; reply in-thread.
- **Loop guards are mandatory** wherever agents can hear each other (or a workflow
  can hear an agent): never re-mention the agent that just mentioned you in the
  same turn; never emit a message-workflow's literal trigger token in output; cap
  retries. The harness's inbound gate (`respond-to`) defaults to **owner-only**,
  which silently drops workflow posts and agent-to-agent mentions — on a closed
  relay run agents with `BUZZ_ACP_RESPOND_TO=anyone`, and know that doing so is
  exactly why the loop guards matter.
- Owner control commands exist in-channel: `!cancel`, `!rotate`, `!shutdown`.
  Put them in the HQ channel topic.

## 4. Model pinning economics

- Set the **pack default to a cheap/fast tier** and override *upward* only where it
  pays: orchestration (synthesis across agents) and high-stakes domains (finance).
  Most routine agents burn tokens for power they never use on a top-tier model.
- Low temperature (≈0.3) for precision roles (finance, review); default (≈0.7) for
  planning/companion roles.
- **Precedence chain** (highest wins): operator env vars → desktop per-agent UI →
  persona frontmatter → pack `defaults` → built-ins. On a headless deployment the
  per-service env (`BUZZ_ACP_MODEL`) *is* the operator level — keep it in sync with
  the pack or accept that env wins.
- The harness is swappable per agent (`BUZZ_ACP_AGENT_COMMAND`: `goose` (default),
  `claude-code`/`claude-agent-acp`, `codex-acp`, `buzz-agent`). Chats, channel
  history, canvases, notes, and mem all live on the relay — **change the model or
  harness, keep the memory.**

## 5. Memory patterns

- `buzz mem` is slug→value, per identity. Reads: `mem ls`, `mem get <slug>`.
- **Always write shared-risk slugs with the CAS flow:** `mem hash <slug>` → edit →
  `mem patch <slug> --base-hash <sha256>`. Exit code 5 = someone else wrote first:
  re-read, re-apply, retry. Reserve plain `mem set` for slugs with exactly one
  writer. Never use `--no-base-hash` where concurrent writers are possible.
- Keep mem values as **small JSON documents with a version field** (e.g.
  `backlog_v1`) so schema evolution is explicit. The `core` slug cannot be removed,
  only emptied.
- Mem is machine state. If a human needs to read it, mirror a human view into the
  channel canvas and state in the persona which one is authoritative.

## 6. Workflow glue

- Workflows are **channel-scoped YAML** (`buzz workflows create --channel <uuid>
  --yaml "$(cat file)"`). Triggers: `message_posted{filter}`, `reaction_added
  {emoji?}`, `diff_posted{filter}`, `schedule{cron | interval ≥60s}`, `webhook`
  (`POST /hooks/{id}`). Actions: `send_message`, `send_dm`, `set_channel_topic`,
  `add_reaction`, `call_webhook`, `request_approval`, `delay`.
- **There is no "run agent" action.** The glue is `send_message` + @mention; the
  agent's mention-trigger does the rest. This keeps the hand-off auditable.
- **Cron is UTC** (5/6/7-field). Use **named weekdays** (`SUN`, `MON`, `FRI`) —
  numeric day-of-week is dialect-ambiguous. Annotate every cron with its local
  time and re-issue `workflows update` after DST shifts if the hour matters.
- **Reaction triggers:** `{{trigger.text}}` is the *emoji character*; the reacted
  message's id is `{{trigger.message_id}}` — pass the id and let the agent fetch
  the message (`buzz messages thread`). The `emoji:` filter is literal string
  equality with the reaction content; verify the client's actual string once.
- Template vars: `{{trigger.text|author|channel_id|timestamp|emoji|message_id}}`,
  `{{steps.ID.output.X}}`; filters `| truncate(n)`, `| npub`. Unknown vars pass
  through **literally** — a typo won't error, it will just print.
- Step ids: `[A-Za-z0-9_]`, ≤64 chars, unique — they become evalexpr variables
  (`steps_<id>_output_approved`), so dashes would parse as subtraction.
- **Approval gate skeleton:** `request_approval{from, message, timeout}` suspends
  the run; approve via desktop or `buzz workflows approve --token <UUID>
  [--approved false]`; branch with `if: "steps_<id>_output_approved == true"` and
  a matching `== false` step so denial/timeout is visible, not silent.
- **Anti-loop rules:** a workflow's output must never contain its own message
  trigger token; a reaction workflow must never react with its own trigger emoji.
- Expect rough edges in scheduling (60s tick loop; on some builds `workflows runs`
  returns `[]`): make every scheduled workflow post a visible message so the
  channel itself is the heartbeat, and give some agent a weekly ritual that would
  notice missed fires.

## 7. Autonomy & approvals

Three tiers — assign one per agent, per action class, in the persona:

1. **Free-posting**: digests, plans, analyses, canvas edits in the agent's own
   channel. No gate.
2. **Approval-gated actions**: money-adjacent, irreversible, or externally visible
   things. Gate with a `request_approval` workflow, or a hard persona rule "only
   after an explicit yes from the owner in this channel". MCP write-tools (vs
   read-tools) are the usual boundary.
3. **Owner-reviewed structural change**: anything that changes the team itself
   goes through `buzz agents draft-create` / `draft-update` — the owner approves a
   prefilled form in the desktop app. Agents *propose*; they never announce a new
   agent as created.

The orchestrator never approves gates itself; gates exist to reach the human.

## 8. Anti-patterns (verified failure modes)

| Anti-pattern | Why it fails |
|---|---|
| Duplicating `[Base]`-layer content in personas | The agent reads it twice per message; drift between copies |
| Secrets or `${VAR}` references in pack MCP config | Env interpolation is **not implemented** on some builds — literals pass through. Use a wrapper script that reads token files |
| SSE-transport MCP servers | Rejected by the ACP runtime; use stdio or streamable_http (bridge remote servers with `mcp-remote`) |
| `SKILL.md` without `name:` + `description:` frontmatter | Skill is **silently skipped**; no fallback to directory name |
| Skills at pack root without copying to `.agents/skills/` | The runtime scans `$AGENT_CWD/.agents/skills/` (and harness-specific dirs), not the pack |
| Setting `GOOSE_MODEL`/model env on the parent process for a multi-agent harness | Overrides *every* persona (operator level wins); pin per subprocess/service instead |
| Expecting sub-key inheritance in `defaults` overrides | Object/array fields replace wholesale; no deep merge |
| `buzz channels list --format compact` | `--format` is a **global** flag: `buzz --format compact channels list` |
| Relying on `workflows runs` for history | Returns `[]` on some builds; design visible heartbeats instead |
| Numeric day-of-week in crons | Dialect-ambiguous; use `SUN`/`MON`/… |
| Trusting `{{trigger.text}}` in reaction workflows | It's the emoji, not the message — use `{{trigger.message_id}}` |
| Leaving `respond-to` at owner-only with workflow/agent mentions in play | Hand-offs silently dropped; set `anyone` (closed relay) or an allowlist |
