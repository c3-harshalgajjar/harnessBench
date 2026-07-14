"""Claude Code adapter.

Headless: `claude -p <prompt> --output-format stream-json --verbose
--dangerously-skip-permissions --mcp-config <json>`. The stream-json output carries
per-turn usage and tool_use events we parse for the native cross-check.

Two modes:
  - proxied (key present): ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN point Claude Code
    at our proxy; we hand it `--model bench-model` and the proxy overwrites
    model + thinking.
  - direct (no key): no base-URL override, so Claude Code uses its own subscription
    (Keychain OAuth) auth; `--model <direct_model_alias>` since there's no proxy to
    rewrite `bench-model`.
"""

from __future__ import annotations

import json

from harnessbench.adapters.base import Adapter
from harnessbench.config import Task


class ClaudeAdapter(Adapter):
    name = "claude"

    def env(self, run_id: str) -> dict[str, str]:
        e = super().env(run_id)
        e.update(
            {
                "ANTHROPIC_BASE_URL": self.proxy_base_url,
                "ANTHROPIC_AUTH_TOKEN": self.proxy_key,
                # Belt-and-suspenders: forward the run-id header via Claude's
                # extra-headers settings env if present.
                "ANTHROPIC_CUSTOM_HEADERS": f"x-harnessbench-run-id: {run_id}",
            }
        )
        return e

    def env_direct(self, run_id: str) -> dict[str, str]:
        # No proxy override — Claude Code falls back to host Keychain subscription auth.
        return {}

    def build_cmd(self, task: Task, run_id: str) -> list[str]:
        return self._cmd(task, self.suite.bench_model_name, "/harnessbench/mcp.json")

    def build_cmd_direct(self, task: Task, run_id: str) -> list[str]:
        # Runs on the host with cwd=work_copy; run_on_host writes mcp.json there.
        return self._cmd(task, self.suite.direct_model_alias, "mcp.json")

    def _cmd(self, task: Task, model: str, mcp_path: str | None) -> list[str]:
        cmd = [
            "claude",
            "-p",
            task.prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
            "--model",
            model,
        ]
        if task.mcp and mcp_path:
            cmd += ["--mcp-config", mcp_path]
        return cmd

    def parse_usage_split(self, stdout: str) -> dict[str, int] | None:
        """Sum stream-json usage into input/output/cache_read/cache_write/total.

        Returns None if no usage blocks were found.
        """
        agg = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        }
        found = False
        for line in stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            usage = (obj.get("message") or {}).get("usage") or obj.get("usage")
            if isinstance(usage, dict):
                found = True
                agg["input_tokens"] += int(usage.get("input_tokens", 0))
                agg["output_tokens"] += int(usage.get("output_tokens", 0))
                agg["cache_read_tokens"] += int(
                    usage.get("cache_read_input_tokens", 0)
                )
                agg["cache_write_tokens"] += int(
                    usage.get("cache_creation_input_tokens", 0)
                )
        if not found:
            return None
        agg["total_tokens"] = agg["input_tokens"] + agg["output_tokens"]
        return agg

    def parse_native_usage(self, stdout: str, stderr: str) -> int | None:
        split = self.parse_usage_split(stdout)
        return split["total_tokens"] if split else None

    def probe_eligible(self) -> bool:
        # Claude Code honors ANTHROPIC_BASE_URL — scored tier.
        return True
