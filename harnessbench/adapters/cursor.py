"""Cursor CLI (cursor-agent) adapter — NEVER scored.

Cursor's hosted models route through Cursor's own gateway and bake the thinking
preset into the model name; there's no documented base-URL override to force traffic
through our proxy. That breaks model+thinking parity, so `probe_eligible()` is always
False — cursor can never enter the scored (proxied) tier.

It CAN still participate in the no-key (direct) path as a self-reported, unverified
data point: `cursor-agent -p ... --output-format json` runs on the host with cursor's
own auth and emits a `usage` block we parse. Those rows land in the report's
self-reported tier (tokens_verified=False, model_parity_ok=False), strictly separated
from proxy-verified numbers so an unpinned token count is never ranked against a
pinned one.
"""

from __future__ import annotations

import json

from harnessbench.adapters.base import Adapter
from harnessbench.config import Task


class CursorAdapter(Adapter):
    name = "cursor"

    def build_cmd(self, task: Task, run_id: str) -> list[str]:
        return self._cmd(task)

    def build_cmd_direct(self, task: Task, run_id: str) -> list[str]:
        # Direct mode: same argv; cursor always uses its own gateway auth.
        return self._cmd(task)

    def env_direct(self, run_id: str) -> dict[str, str]:
        # No proxy override — cursor authenticates against its own hosted gateway.
        return {}

    def _cmd(self, task: Task) -> list[str]:
        cmd = [
            "cursor-agent",
            "-p",
            task.prompt,
            "--output-format",
            "json",
            "--force",
            "--trust",
        ]
        if task.mcp:
            cmd += ["--mcp-config", "mcp.json"]
        return cmd

    def parse_usage_split(self, stdout: str) -> dict[str, int] | None:
        """Parse cursor-agent's final JSON `usage` block.

        Shape observed on 2026.07.09:
          {"usage": {"inputTokens": N, "outputTokens": N,
                     "cacheReadTokens": N, "cacheWriteTokens": N}, ...}
        cursor-agent may emit multiple JSON objects (one per event) with `--output-format
        json`; we take the last object carrying a usage block.
        """
        last: dict[str, int] | None = None
        for line in stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            usage = obj.get("usage")
            if isinstance(usage, dict):
                inp = int(usage.get("inputTokens", 0))
                out = int(usage.get("outputTokens", 0))
                last = {
                    "input_tokens": inp,
                    "output_tokens": out,
                    "cache_read_tokens": int(usage.get("cacheReadTokens", 0)),
                    "cache_write_tokens": int(usage.get("cacheWriteTokens", 0)),
                    "total_tokens": inp + out,
                }
        return last

    def parse_native_usage(self, stdout: str, stderr: str) -> int | None:
        split = self.parse_usage_split(stdout)
        return split["total_tokens"] if split else None

    def probe_eligible(self) -> bool:
        # No base-URL override => cannot enforce parity => never scored.
        return False
