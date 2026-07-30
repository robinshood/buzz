#!/usr/bin/env bash
# Era Context MCP bridge: remote MCP -> stdio, for the agent harness.
# No secrets live in this file or in the persona pack ("${VAR}" interpolation is
# not implemented in this buzz build) — everything comes from /etc/lifeops/era.env:
#   ERA_MCP_URL=https://...            (required)
#   ERA_AUTH_HEADER=Authorization: Bearer <token>   (optional; else OAuth via mcp-remote)
# First OAuth run is interactive — complete it via SSH port-forward, or copy
# ~/.mcp-auth to the service user (mode 600). See ../VPS-SETUP.md §6.
set -euo pipefail

ENV_FILE="${ERA_ENV_FILE:-/etc/lifeops/era.env}"
# shellcheck disable=SC1090
source "$ENV_FILE"

if [[ -z "${ERA_MCP_URL:-}" ]]; then
  echo "era-mcp.sh: ERA_MCP_URL is not set in $ENV_FILE" >&2
  exit 1
fi

args=(-y mcp-remote "$ERA_MCP_URL")
if [[ -n "${ERA_AUTH_HEADER:-}" ]]; then
  args+=(--header "$ERA_AUTH_HEADER")
fi

exec npx "${args[@]}"
