# Garmin-PT persona-pakke — Coach + Forsker på Buzz

To agenter for #trening-kanalen på din egen Buzz-relay:

- **Coach** (Sonnet 5) — PT-en. Leser garmin-pt-MCP-verktøyene, styrer
  ukesplanen readiness-basert, og pusher økter til Garmin-kalenderen **kun
  etter ditt OK** i tråden.
- **Forsker** (Opus 5) — research-agenten. Websøk mot primærlitteratur,
  kalibrert konfidens, DOI/PMID-referanser.

Begge kjører på `claude-agent-acp`-runtimen (Claude Agent SDK over ACP) via
buzz-acp-harnesset. Tidsplanene (mandagsplan, daglig morgensjekk,
søndagsoppsummering) ligger som workflow-YAML i `../workflows/` og kjøres
relay-side.

Forutsetninger: garmin-pt-datalaget kjører (se `../README.md`), lokal
buzz-relay oppe (`just relay`), `buzz`/`buzz-admin`/`buzz-acp` bygget
(`cargo build --release -p buzz-cli -p buzz-admin -p buzz-acp`), og en
`ANTHROPIC_API_KEY`.

## 1. Tilpass og valider pakken

```bash
# .mcp.json: bytt /ABSOLUTT/STI/TIL/garmin-pt med ekte sti (env-var-interpolering
# støttes ikke i mcp-env ennå — bruk absolutt sti)
$EDITOR pack/.mcp.json

buzz pack validate garmin-pt/pack
buzz pack inspect garmin-pt/pack     # sjekk at begge personas og MCP-serveren vises
```

Installer: kopiér `pack/` til `~/.buzz/packs/com.robin.garmin-pt/`, eller
bruk Desktop-appens Agents-sidebar («New agent» → importer pakke) hvis du
foretrekker GUI.

## 2. Mint agent-nøkler (egne identiteter, ikke din)

```bash
buzz-admin generate-key   # → Coach   (ta vare på nsec + pubkey)
buzz-admin generate-key   # → Forsker
```

Sett display-navn på agent-brukerne slik at de matcher personaene
(**Coach** og **Forsker**) — workflow-@mentions løses mot *eksakt*
display-navn blant kanalmedlemmene; tvetydige navn vekker ingen.

## 3. Kanal og medlemskap

```bash
buzz channels create --name trening            # eller bruk eksisterende
buzz channels add-member --channel "$CHANNEL" --pubkey "$COACH_PUBKEY" --role member
buzz channels add-member --channel "$CHANNEL" --pubkey "$FORSKER_PUBKEY" --role member
```

Hopper du over add-member sitter agenten stille («discovered 0 channels»).

## 4. Kjør harnessene (standalone, IKKE som desktop-barn)

Desktop-startede agenter dør når appen lukkes. Kjør to buzz-acp-instanser
selv, én per agent:

```bash
npm install -g @agentclientprotocol/claude-agent-acp

# Coach
BUZZ_RELAY_URL=ws://localhost:3000 \
BUZZ_PRIVATE_KEY=$COACH_NSEC \
BUZZ_AUTH_TAG=$COACH_AUTH_TAG \
BUZZ_ACP_AGENT_COMMAND=claude-agent-acp \
BUZZ_ACP_RESPOND_TO=owner-only \
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
buzz-acp

# Forsker: samme, med Forskers nøkler
```

For drift: legg hver av dem i en launchd-plist under
`~/Library/LaunchAgents/` (`KeepAlive=true`, `RunAtLoad=true`, env-variablene
i `EnvironmentVariables`), så overlever de reboot og GUI-lukking. Husk at
`ANTHROPIC_API_KEY` da ligger i plisten — `chmod 600`.

## 5. Registrer workflowene

```bash
buzz workflows create --channel "$CHANNEL_UUID" --yaml garmin-pt/workflows/mandagsplan.yml
buzz workflows create --channel "$CHANNEL_UUID" --yaml garmin-pt/workflows/morgensjekk.yml
buzz workflows create --channel "$CHANNEL_UUID" --yaml garmin-pt/workflows/sondagsoppsummering.yml
buzz workflows list --channel "$CHANNEL_UUID"
```

Cron-uttrykkene er **UTC** og driver én time med sommertid (kommentert i
hver fil). Test en workflow umiddelbart uten å vente på cron:
`buzz workflows trigger --workflow <uuid>`.

## 6. Røyk-test

1. `@Coach status?` i #trening → forvent svar som siterer `data_basis`
   (eller en tydelig kalibrerer-/no_data-beskjed).
2. `@Forsker hva sier evidensen om HRV-styrt trening?` → forvent konklusjon
   med konfidensmerke og referanser.
3. `buzz workflows trigger` på mandagsplan → Coach skal foreslå plan og
   IKKE pushe; svar «kjør» og verifiser at øktene dukker opp i
   Garmin Connect-kalenderen (første push: sjekk at øktformatet ser riktig
   ut på klokka — id-kodene i workout-byggeren er medium konfidens).
4. DM Coach fra mobilen.

## Kjente begrensninger

- **Nede-agent mister cron-vekkinger:** meldingen står i kanalen, men en
  agent som var nede da den kom, svarer ikke av seg selv — ping på nytt.
  Derfor launchd med KeepAlive.
- **Relayen må kjøre** for at cron skal fyre (schedulering er relay-side).
- **Engrams er private per agent:** Forskers funn deles som kanalmeldinger,
  ikke via minne. Du kan lese agentenes minne selv: `buzz mem ls --agent <pubkey>`.
- Persona-prompten leveres i dag som `[System]`-prefiks på brukermeldingen
  (kjent gap i harnesset, PF-1) — fungerer, men ikke rediger personaen til å
  avhenge av streng system/user-separasjon.
