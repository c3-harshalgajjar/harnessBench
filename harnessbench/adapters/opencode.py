"""opencode adapter.

Headless: `opencode run <prompt> --model anthropic/bench-model --format json`.
The `--format json` stream carries usage + tool events for the native cross-check.

Base-URL override: opencode reads provider config from a generated opencode.json in
the workspace, where we set `provider.anthropic.options.baseURL` to the proxy and
register a `bench-model` model id. The entrypoint writes that file before dispatch.
"""

from __future__ import annotations

import json

from harnessbench.adapters.base import Adapter
from harnessbench.config import Task


class OpencodeAdapter(Adapter):
    name = "opencode"

    def env(self, run_id: str) -> dict[str, str]:
        e = super().env(run_id)
        # opencode honors these standard Anthropic env vars for the built-in provider.
        e.update(
            {
                "ANTHROPIC_BASE_URL": self.proxy_base_url,
                "ANTHROPIC_API_KEY": self.proxy_key,
            }
        )
        return e

    def build_cmd(self, task: Task, run_id: str) -> list[str]:
        return [
            "opencode",
            "run",
            task.prompt,
            "--model",
            f"anthropic/{self.suite.bench_model_name}",
            "--format",
            "json",
            "--pure",  # skip external plugins for a neutral run
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
            tokens = obj.get("tokens") or (obj.get("usage") or {})
            if isinstance(tokens, dict) and tokens:
                inp = int(tokens.get("input", tokens.get("input_tokens", 0)))
                out = int(tokens.get("output", tokens.get("output_tokens", 0)))
                if inp or out:
                    found = True
                    total += inp + out
        return total if found else None

    def probe_eligible(self) -> bool:
        return True
