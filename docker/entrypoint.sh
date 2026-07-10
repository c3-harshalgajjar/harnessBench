#!/usr/bin/env bash
# Container entrypoint: neutralize steering, materialize MCP config, then exec the
# harness argv. Runs once per (task x harness x trial) invocation.
#
# Why this exists: harnesses silently pick up steering files (CLAUDE.md, AGENTS.md,
# .cursorrules, opencode.json, global config dirs) and per-user settings that would
# make a cross-harness comparison meaningless. We scrub every known steering source
# from both /work and the container HOME before the harness starts, so the only
# instruction any harness sees is the task prompt itself.
#
# It also writes the task's MCP config (passed as HARNESSBENCH_MCP_JSON) to a fixed
# path the adapters point at, and forces a clean HOME so no host config leaks in.

set -euo pipefail

# --- 1. Neutralize steering files in the workspace -------------------------
# These are the files coding agents auto-load as "project instructions". Removing
# them ensures the prompt is the sole instruction channel across all harnesses.
STEERING_NAMES=(
    "CLAUDE.md"
    "CLAUDE.local.md"
    "AGENTS.md"
    "AGENT.md"
    ".cursorrules"
    ".windsurfrules"
    ".github/copilot-instructions.md"
    "opencode.json"
    "opencode.jsonc"
    ".opencode.json"
    "pi.json"
    ".pi.json"
    ".codex.md"
    "codex.md"
)
for name in "${STEERING_NAMES[@]}"; do
    find /work -name "$name" -type f -delete 2>/dev/null || true
done
# Directory-shaped steering (rules dirs, agent configs).
for dir in ".cursor/rules" ".claude" ".opencode" ".pi" ".codex"; do
    rm -rf "/work/${dir}" 2>/dev/null || true
done

# --- 2. Clean HOME so no per-user harness config is inherited --------------
# The container gets a throwaway HOME; nothing from any host mount should shadow it.
export HOME=/root
mkdir -p "$HOME"
for cfg in ".claude" ".claude.json" ".config/opencode" ".config/pi" ".codex" \
           ".config/anthropic" ".config/cursor"; do
    rm -rf "${HOME:?}/${cfg}" 2>/dev/null || true
done

# --- 3. Materialize the task's MCP config ----------------------------------
# The runner passes a Claude-style mcpServers JSON blob. Drop it where the
# adapters expect it (claude --mcp-config, opencode's config, etc.).
mkdir -p /harnessbench
if [[ -n "${HARNESSBENCH_MCP_JSON:-}" ]]; then
    printf '%s' "$HARNESSBENCH_MCP_JSON" > /harnessbench/mcp.json
else
    printf '{"mcpServers":{}}' > /harnessbench/mcp.json
fi

# --- 4. Make git quiet + identity present (some harnesses commit) ----------
git config --global user.email "bench@harnessbench.local" 2>/dev/null || true
git config --global user.name "harnessbench" 2>/dev/null || true
git config --global init.defaultBranch main 2>/dev/null || true

# --- 5. Exec the harness argv ----------------------------------------------
# All args after the image name land here. exec so signals/exit code pass through.
exec "$@"
