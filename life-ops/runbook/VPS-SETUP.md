# VPS Setup — relay, agents, Era Context

End-to-end path from an empty VPS to the always-on Life-Ops team. Follow in order;
each step ends in something verifiable. Commands assume Ubuntu LTS and a shell on
the VPS unless noted. Where flags are version-sensitive, confirm with `--help` on
your build (see §10 on HEAD drift).

## 1. Provision

- VPS with **≥ 2 vCPU / 4 GB RAM** (relay stack + four harness processes + Node),
  a DNS A record (`buzz.example.com`), ports 80/443 open.
- Install: Docker + Compose **≥ 2.24.4**, Node **≥ 20** (for `mcp-remote` and the
  Claude ACP adapter), and either the Rust toolchain or prebuilt `buzz`,
  `buzz-acp`, `buzz-admin` binaries copied to `/usr/local/bin/`
  (`cargo build --release -p buzz-cli -p buzz-acp -p buzz-admin`).
- Create the service user + directories:

```bash
sudo useradd -r -m -d /srv/lifeops lifeops
sudo mkdir -p /srv/lifeops/{agents/{los,ore,vaskebjorn,kurv},prompts,bin} /etc/lifeops
sudo chown -R lifeops:lifeops /srv/lifeops
sudo chmod 700 /etc/lifeops
```

## 2. Relay (deploy/compose)

```bash
cd deploy/compose
cp .env.example .env
$EDITOR .env    # replace every CHANGE_ME (openssl rand -hex 32); set your domain
BUZZ_COMPOSE_TLS=true ./run.sh start
curl -fsS "https://buzz.example.com/_liveness" && ./run.sh status
```

- **Closed relay:** create your owner identity in the desktop app first, then put
  its **64-char hex pubkey** in `RELAY_OWNER_PUBKEY` in `.env`.
- Set `BUZZ_AUTO_MIGRATE=true` for first boot (or run `buzz-admin migrate`).
- Keep `BUZZ_RELAY_PRIVATE_KEY`, DB/Redis/S3 secrets stable across restarts.

**Done when:** `/_liveness` returns OK over TLS.

## 3. Desktop connect, preview features, channels

1. Desktop app → add community `wss://buzz.example.com`.
2. Settings → preview features → enable **Workflows** (Pulse/Projects optional).
3. Create channels: `#agent-hq` (private), `#hushold`, `#handleliste`,
   `#okonomi` (**private**), `#automasjon-backlog`.
4. Paste the initial canvases: shopping list skeleton in `#handleliste`, the
   rangeringsliste seed table from [`../PLAN.md`](../PLAN.md) §5 in
   `#automasjon-backlog`.

**Done when:** all five channels exist and you can post in them from desktop.

## 4. Agent identities

Mint one identity per agent (on the VPS, pointed at the relay):

```bash
buzz-admin mint-token --name los  # repeat: ore, vaskebjorn, kurv; check --help for scopes
```

Store per agent in `/etc/lifeops/<name>.env` (root-owned, mode 600) — see
[`systemd/agents/`](systemd/agents/) for the templates. Add each agent to its
channels from the desktop app (private channels have no member-management API on
this build — the UI is the path).

**Done when:** four env files exist and each agent appears as a channel member.

## 5. Harness runtime (Claude Code under every agent)

```bash
sudo npm install -g @agentclientprotocol/claude-agent-acp
```

- `BUZZ_ACP_AGENT_COMMAND=claude-agent-acp` (the `claude-code`/`claude-agent-acp`
  names are treated as the same zero-arg runtime family by `buzz-acp`).
- **Auth:** an `ANTHROPIC_API_KEY` in the service env is the well-trodden path. A
  Claude subscription OAuth token (`claude setup-token` →
  `CLAUDE_CODE_OAUTH_TOKEN`) may work with the ACP adapter — verify against your
  plan's terms before relying on it for an always-on service.
- **Model pinning is per service** (`BUZZ_ACP_MODEL` in each env file). Operator
  env outranks pack/persona values — keep them in sync deliberately.

## 6. Era Context bridge (Øre only)

Era Context is a remote MCP server; the harness only speaks stdio/streamable_http,
so bridge it with `mcp-remote` via the wrapper script (no secrets inline):

```bash
sudo cp life-ops/runbook/bin/era-mcp.sh /srv/lifeops/bin/ && sudo chmod 755 /srv/lifeops/bin/era-mcp.sh
sudo tee /etc/lifeops/era.env >/dev/null <<'EOF'
ERA_MCP_URL=https://<your-era-context-mcp-endpoint>
# Optional, if Era gives you a static bearer token:
# ERA_AUTH_HEADER=Authorization: Bearer <token>
EOF
sudo chmod 600 /etc/lifeops/era.env
```

- **OAuth first run is interactive:** `mcp-remote` opens a browser flow. Do it
  once via `ssh -L 3334:localhost:3334 vps` (or run the bridge locally and copy
  `~/.mcp-auth` to the `lifeops` user, mode 600).
- **Headless wiring:** this build has no pack auto-load in `buzz-acp`, so give the
  Claude runtime the server via a project-level `.mcp.json` in Øre's working
  directory (`/srv/lifeops/agents/ore/.mcp.json`):

```json
{ "mcpServers": { "era-context": { "command": "/srv/lifeops/bin/era-mcp.sh" } } }
```

**Done when:** running `/srv/lifeops/bin/era-mcp.sh` as `lifeops` handshakes
without an interactive prompt.

## 7. Per-agent services

Render the persona bodies to prompt files, seed skills, install the unit:

```bash
life-ops/runbook/bin/render-prompts.sh life-ops/pack/agents /srv/lifeops/prompts
for a in los ore vaskebjorn kurv; do
  sudo -u lifeops mkdir -p /srv/lifeops/agents/$a/.agents/skills /srv/lifeops/agents/$a/.claude/skills
  sudo -u lifeops cp -r life-ops/pack/skills/buzz-team-design /srv/lifeops/agents/$a/.agents/skills/
  sudo -u lifeops cp -r life-ops/pack/skills/buzz-team-design /srv/lifeops/agents/$a/.claude/skills/
done
sudo cp life-ops/runbook/systemd/buzz-agent@.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now buzz-agent@kurv    # Wave 0: Kurv first
```

Key env per service (see [`systemd/agents/los.env.example`](systemd/agents/los.env.example)):
`BUZZ_RELAY_URL`, `BUZZ_PRIVATE_KEY`, `BUZZ_ACP_AGENT_COMMAND=claude-agent-acp`,
`BUZZ_ACP_SYSTEM_PROMPT_FILE`, `BUZZ_ACP_SUBSCRIBE`, `BUZZ_ACP_MODEL`,
`BUZZ_ACP_RESPOND_TO=anyone` (closed relay — the owner-only default silently drops
workflow posts and agent-to-agent mentions), `AGENT_CWD=/srv/lifeops/agents/<name>`.
Skill auto-copy from packs is *planned*, not implemented — hence the manual seed.

**Done when (Wave 0):** with your laptop closed, @Kurv answers a mention in
`#handleliste`; `@Øre`-style non-ASCII mentions resolve (else rename to `Oere`).

## 8. Workflows

Install per [`../workflows/README.md`](../workflows/README.md) (owner key in env):
find channel UUIDs with `buzz --format compact channels list`, then
`buzz workflows create --channel <uuid> --yaml "$(cat <file>)"` for each of the
seven files. Manually `workflows trigger` the schedule-type ones once; verify the
🛒 reaction literal against the relay debug log on first real use.

**Done when:** each installed workflow has fired (manually or on schedule) and the
mentioned agent responded.

## 9. Backups

Run `deploy/compose/run.sh backup-hint` and cover: Postgres, MinIO, git volumes,
`deploy/compose/.env`, the relay private key, owner + agent nsecs
(`/etc/lifeops/*.env`), Era token + `~lifeops/.mcp-auth`, and this repo. Keep one
copy off the VPS. Rotate the Era token on a calendar schedule; `!rotate` in
`#agent-hq` re-keys a compromised agent.

## 10. HEAD drift re-check

These assets were authored against a clone a few days behind `main`. Before
deploying, check on your HEAD: (a) whether `buzz-acp` gained persona-pack
auto-load (would replace §6's `.mcp.json` fallback and §7's prompt rendering),
(b) whether `buzz workflows runs` now returns history (relaxes the
visible-heartbeat rule), (c) exact `buzz-admin mint-token` / `buzz-acp` flags
(`--help`).
