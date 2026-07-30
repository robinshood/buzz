# Life-Ops Automation Plan

A plan for running personal life operations — shopping lists, household planning,
personal finance, and a self-feeding automation backlog — as a **Buzz agent team**,
with Claude Code as the harness under every agent.

Everything here targets behavior verified in this repository. One caveat applies
throughout: the working clone used to author these assets was a few days behind
`main` at the time; before deploying, re-check the noted items against your HEAD
(see [Runbook §10](runbook/VPS-SETUP.md)).

---

## 1. Principles

1. **Agents are teammates, not bots.** Each has its own keypair, channel memberships,
   instructions, and audit trail. Add them to channels the way you'd add a person.
2. **Pin models per agent.** Routine agents run a cheap model; orchestration and
   finance run a strong one. The pack encodes this (`model:` per persona); the
   harness enforces it per service. Swap the harness later — the chats and memory stay.
3. **One orchestrator, many specialists** (the "Chief Agent Officer" pattern, shipped
   in Buzz as `examples/meadow-core`'s Skip): Los delegates and ranks work; the
   specialists own their domains.
4. **State lives in the right surface.** Canvas = the *current* mutable document of a
   channel. Notes (NIP-23) = dated, durable reports. `buzz mem` = agent-private
   machine state with compare-and-swap patching. Messages = the audit trail.
5. **Autonomy is tiered.** Free-posting for low stakes (digests, plans); workflow
   `request_approval` gates for money-adjacent actions; owner-reviewed drafts
   (`buzz agents draft-create/draft-update`) for structural changes to the team itself.
6. **The backlog feeds itself.** Every manual process gets scored onto the
   rangeringsliste; a weekly ritual re-ranks it and nominates the next automation.

## 2. Channels

Created by the owner account on a **closed relay** (`RELAY_OWNER_PUBKEY` set).
ASCII channel names; Norwegian conversation.

| Channel | Visibility | Members | Purpose | State surfaces |
|---|---|---|---|---|
| `#agent-hq` | private | you + all agents | Coordination, delegation, harness control (`!cancel`, `!rotate`, `!shutdown`), workflow announcements | mem (Los): `backlog_v1` |
| `#hushold` | open | you, Vaskebjørn, Los | Cleaning + laundry planning | canvas = this week's plan; notes = archive; mem (Vaskebjørn): `rotasjon_state` |
| `#handleliste` | open | you, Kurv, Los | Shopping list | canvas = **the** list (single source of truth) |
| `#okonomi` | **private** | you, Øre, Los | Finance digests, alerts, investment watch, gated deep-dives | notes = weekly/monthly reports; mem (Øre): `budsjett_rammer`, `investering_watchlist` |
| `#automasjon-backlog` | open | you + all agents | Intake of manual processes, the rangeringsliste | canvas = ranked table; mem (Los): `backlog_v1` |

## 3. Agent roster (pack [`pack/`](pack/), id `com.robinshood.life-ops`)

| Agent | Role | Model tier | Channels | Triggers | MCP | Autonomy |
|---|---|---|---|---|---|---|
| **Los** | Orchestrator / CAO — delegates, never does domain work; owns the rangeringsliste and the weekly review | opus | `#agent-hq`, `#automasjon-backlog` | mentions + all messages | — | Coordinates freely; team changes only via owner-reviewed drafts; never approves gates itself |
| **Øre** | Finance — expenses, budget, recurring charges, investment watch via **Era Context** | opus, temp 0.3 | `#okonomi` | mentions + keywords (budsjett, utgifter, investering, regning, sparing) | Era Context (stdio bridge) | Read-only posts freely; **any Era write tool and the monthly deep-dive require explicit approval**; investments = analysis only, never execution |
| **Vaskebjørn** | Household — weekly cleaning/laundry plan, rotation memory | sonnet | `#hushold` | mentions + keywords (vask, klesvask, rengjøring, husarbeid) | — | Free-posting |
| **Kurv** | Shopping — maintains the `#handleliste` canvas, digests, dedupe/categorize | sonnet | `#handleliste` | mentions + keywords (handleliste, handle, matvarer) | — | Free-posting; canvas is its only write target |

Machine names are ASCII (`los`, `ore`, `vaskebjorn`, `kurv`); display names are
Norwegian. Wave 0 includes a test that `@Øre` mentions resolve on your build —
fall back to display name `Oere` if not. Model ids in the pack
(`anthropic:claude-opus-5` / `anthropic:claude-sonnet-5`) are placeholders —
set them to whatever your subscription offers.

## 4. Workflows ([`workflows/`](workflows/))

Workflows are **channel-scoped**; the engine has **no "run agent" action**, so every
hand-off is a `send_message` that @-mentions the responsible agent. All crons are
**UTC** (Oslo times below assume CEST, UTC+2; each YAML carries a DST note).

| # | File | Trigger | What happens |
|---|---|---|---|
| 1 | `hushold/ukeplan-vask.yaml` | Sun 18:00 Oslo | Prompts @Vaskebjørn to plan the week (canvas), archive last week (notes) |
| 2 | `handleliste/reaksjon-legg-til.yaml` | 🛒 reaction | Acks ✅, hands the reacted message id to @Kurv to extract items into the canvas |
| 3 | `handleliste/fredagsdigest.yaml` | Fri 15:30 Oslo | @Kurv posts the pre-shopping digest (grouped, deduped, staples check) |
| 4 | `okonomi/ukesrapport.yaml` | Mon 07:00 Oslo | @Øre posts the weekly finance digest, publishes the full report as a note |
| 5 | `okonomi/manedsrapport-godkjenning.yaml` | 1st of month 08:00 Oslo | **Approval gate** (48h) → approved: @Øre runs the deep-dive; denied/timeout: skip notice |
| 6 | `automasjon-backlog/intake.yaml` | message contains `!auto` | Acks 📋 and notifies @Los to score the proposal |
| 7 | `automasjon-backlog/ukentlig-rangering.yaml` | Sun 17:00 Oslo | @Los re-ranks the rangeringsliste, summarizes the week, nominates the next automation (runs an hour before #1 so the review lands first) |

Approve/deny gates from the desktop Workflows UI (a preview feature — enable it in
Settings) or `buzz workflows approve --token <UUID> [--approved false --note "..."]`.

## 5. Rangeringslisten (the ranked automation backlog)

Every manual process gets scored:

```
Score = Frekvens × Smerte × Automatiserbarhet − 4 × Risiko
        (1–5)      (1–5)     (1–5)                (0–5)
```

*Frekvens* = how often you do it; *Smerte* = time/annoyance; *Automatiserbarhet* =
tractability with current Buzz + Claude tooling; *Risiko* = blast radius of an
automation error (money, privacy, irreversibility). Ties break toward lower risk.

Seed ranking (v1):

| # | Process | F | S | A | R | Score | Status |
|---|---|---|---|---|---|---|---|
| 1 | Handleliste (capture + digest) | 5 | 3 | 5 | 0 | 75 | Wave 1 |
| 2 | Ukentlig vaskeplan/klesvask | 4 | 3 | 5 | 0 | 60 | Wave 1 |
| 3 | Ukentlig utgiftsdigest (Era, read-only) | 4 | 4 | 4 | 2 | 56 | Wave 2 |
| 4 | Abonnements-/fasttrekk-revisjon | 2 | 4 | 5 | 1 | 36 | Wave 2 |
| 5 | Månedlig dyp økonomirapport + investeringsvurdering | 2 | 5 | 4 | 3 | 28 | Wave 2 (gated) |
| 6 | Regningspåminnelser (forfall) | 3 | 3 | 3 | 2 | 19 | Wave 3 |
| 7 | Innboks-/påminnelsestriage | 4 | 3 | 2 | 3 | 12 | Wave 3 — Claude Code side (needs Gmail tooling) |
| 8 | Strømsparing (spotpris) | 3 | 3 | 2 | 3 | 6 | **Deferred by decision** — re-scored weekly |

The human-readable table lives in the `#automasjon-backlog` **canvas**; machine
state in Los's mem slug **`backlog_v1`**, always written via the CAS flow
(`buzz mem hash` → `buzz mem patch --base-hash …`; retry on exit code 5). Intake:
post `!auto <beskrivelse>` in the channel (workflow 6). Weekly ritual: workflow 7.

## 6. Build it in Buzz, or through Claude Code?

> **Runs while I sleep → Buzz. Needs my hands or deep tools → Claude Code.
> Both → Buzz triggers, Claude executes, buzz-cli reports back.**

**Buzz (VPS agents + workflows)** when it is recurring or event-driven; must run
with the laptop closed; is conversational or multi-agent; needs a channel audit
trail or an approval gate; or its state belongs in canvas/notes/mem.

**Claude Code (interactive session)** when it is one-off deep analysis; touches this
repo (authoring workflows/personas, harness debugging — quality gates live here);
needs your claude.ai connectors and skills (Gmail, Notion, deep-research, the
locally-authenticated Era connector); or needs live iteration with you.

**The hybrid loop** is the default for heavy work: a Buzz workflow fires on
schedule and posts a nudge → an agent handles it in-channel, or you (or a scheduled
Claude session) do the heavy lifting in Claude Code → results return via
`buzz messages send` / `notes create` / `canvas set`, so the channel stays the
system of record. Era Context is deliberately wired in **both** places.

Authoring new automations is itself split: **author + validate + version-control in
Claude Code** (this repo, `life-ops/verify`), **execute in Buzz**.

## 7. Rollout waves

| Wave | Scope | Done when |
|---|---|---|
| **0 — Foundation** | VPS + relay (compose, TLS, closed mode); channels created; keys minted; **Kurv only** deployed | @Kurv answers a mention with your laptop closed; `@Øre` mention-resolution tested; one manual `workflows trigger` round-trips |
| **1 — Top-3 + rituals** | Los + Vaskebjørn deployed; workflows 1, 2, 3, 6, 7; rangeringsliste seeded (canvas + `backlog_v1`) | Each scheduled workflow has fired twice unattended; 🛒 reaction string verified against relay log |
| **2 — Finance** | Era bridge on VPS; Øre deployed; workflows 4, 5; budget frames in mem | Weekly digest posts unattended; one monthly gate **approved** and one **denied/timed out**, both branching correctly |
| **3 — Expansion** | Candidates 4–7 from the seed table, via the weekly ritual | First new automation graduates from the rangeringsliste into a committed workflow through a Claude Code session |

## 8. Risks

| Risk | Mitigation |
|---|---|
| Era credentials on the VPS | Root-owned mode-600 files under `/etc/lifeops/`; wrapper script holds no secret inline; closed relay; rotate on schedule (runbook backup checklist) |
| Scheduler roughness; `workflows runs` returns `[]` on this build (no CLI run history) | Every scheduled workflow posts a visible message — its own heartbeat; Los's weekly review doubles as missed-fire detection; re-check observability on HEAD |
| Reaction emoji delivered ≠ `🛒` literal | Wave-1 check against relay debug log ("Reaction emoji mismatch"); fix via `workflows update` |
| Agent-to-agent mention loops (`respond-to anyone` + Los on all-messages) | Persona loop guards (never re-mention your mentioner in the same turn; one mention per hand-off); never emit the literal `!auto` token; `!cancel` documented in `#agent-hq` |
| DST drift on crons | Header comments in every YAML; re-issue `workflows update` after clock changes if the hour matters |
| Cost of opus-tier agents | Only Los + Øre; weekly cadences, not daily; economics documented in the skill |
| Non-ASCII mention (`@Øre`) | Wave-0 test; rename fallback `Oere` |
| Clone-behind-HEAD | All designs target verified behavior; runbook §10 re-checks pack auto-load and observability before deploy |

## 9. References

- Workflow schema: `crates/buzz-workflow/src/schema.rs` (triggers/actions/validation)
- Persona pack spec: `crates/buzz-persona/PERSONA_PACK_SPEC.md`
- Orchestrator example: `examples/meadow-core/agents/skip.persona.md`
- Harness env surface: `crates/buzz-acp/src/config.rs` (`BUZZ_ACP_*`)
- VPS relay bundle: `deploy/compose/`
- Skill: `.claude/skills/buzz-team-design/SKILL.md` (mirrored in `.agents`, `.codex`, `.goose`)
