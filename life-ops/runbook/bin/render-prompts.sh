#!/usr/bin/env bash
# Render persona bodies for the headless harness: strip the YAML frontmatter from
# each <pack>/agents/*.persona.md and write the markdown body (the system prompt)
# to <outdir>/<name>.md, for use with BUZZ_ACP_SYSTEM_PROMPT_FILE.
#
# Usage: render-prompts.sh <agents-dir> <outdir>
#   e.g. render-prompts.sh life-ops/pack/agents /srv/lifeops/prompts
set -euo pipefail

AGENTS_DIR="${1:?usage: render-prompts.sh <agents-dir> <outdir>}"
OUTDIR="${2:?usage: render-prompts.sh <agents-dir> <outdir>}"
mkdir -p "$OUTDIR"

shopt -s nullglob
found=0
for f in "$AGENTS_DIR"/*.persona.md; do
  found=1
  name="$(basename "$f" .persona.md)"
  # Body = everything after the second '---' line (frontmatter delimiters).
  awk 'BEGIN{fence=0} /^---[[:space:]]*$/{fence++; next} fence>=2{print}' "$f" \
    > "$OUTDIR/$name.md"
  if [[ ! -s "$OUTDIR/$name.md" ]]; then
    echo "render-prompts.sh: $f produced an empty prompt (missing frontmatter fences?)" >&2
    exit 1
  fi
  echo "rendered $OUTDIR/$name.md"
done

if [[ "$found" -eq 0 ]]; then
  echo "render-prompts.sh: no *.persona.md files in $AGENTS_DIR" >&2
  exit 1
fi
