"""pi adapter.

Headless: `pi -p <prompt> --mode json --model anthropic/bench-model`. pi encodes
thinking level in the model string (`model:high`), but that's irrelevant here: the
proxy overwrites thinking server-side, so we pass the bare `bench-model` and let the
route decide. Base-URL override via provider config the entrypoint writes.
"""

from __future__ import annotations

import json

from harnessbench.adapters.base import Adapter
from harnessbench.config import Task


class PiAdapter(Adapter):
    name = "pi"

    def env(self, run_id: str) -> dict[str, str]:
        e = super().env(run_id)
        e.update(
            {
                "ANTHROPIC_BASE_URL": self.proxy_base_url,
                "ANTHROPIC_API_KEY": self.proxy_key,
            }
        )
        return e

    def build_cmd(self, task: Task, run_id: str) -> list[str]:
        return [
            "pi",
            "-p",
            task.prompt,
            "--mode",
            "json",
            "--model",
            f"anthropic/{self.suite.bench_model_name}",
            "--no-approve",  # ignore project-local steering files for a neutral run
        ]

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
            usage = obj.get("usage") or {}
            if isinstance(usage, dict) and usage:
                inp = int(usage.get("input_tokens", usage.get("input", 0)))
                out = int(usage.get("output_tokens", usage.get("output", 0)))
                if inp or out:
                    found = True
                    total += inp + out
        return total if found else None

    def probe_eligible(self) -> bool:
        # Eligible IF pi honors ANTHROPIC_BASE_URL for the anthropic provider. The
        # runner re-probes at container build; default optimistic here.
        return True
