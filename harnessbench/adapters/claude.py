"""Claude Code adapter.

Headless: `claude -p <prompt> --output-format stream-json --verbose
--dangerously-skip-permissions --mcp-config <json>`. The stream-json output carries
per-turn usage and tool_use events we parse for the native cross-check.

Base-URL override: ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN point Claude Code at our
proxy. We hand it `--model bench-model`; the proxy overwrites model + thinking.
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

    def build_cmd(self, task: Task, run_id: str) -> list[str]:
        cmd = [
            "claude",
            "-p",
            task.prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
            "--model",
            self.suite.bench_model_name,
        ]
        if task.mcp:
            cmd += ["--mcp-config", "/harnessbench/mcp.json"]
        return cmd

    def parse_native_usage(self, stdout: str, stderr: str) -> int | None:
        total = 0
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
                total += int(usage.get("input_tokens", 0)) + int(
                    usage.get("output_tokens", 0)
                )
        return total if found else None

    def probe_eligible(self) -> bool:
        # Claude Code honors ANTHROPIC_BASE_URL — scored tier.
        return True
