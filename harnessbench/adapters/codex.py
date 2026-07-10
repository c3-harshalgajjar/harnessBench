"""Codex CLI adapter.

Headless: `codex exec <prompt> --model bench-model`. Codex routes through OpenAI by
default; to score it it must accept an OpenAI-compatible base URL pointed at the
proxy (LiteLLM exposes both /v1/chat/completions and /v1/messages). If the installed
codex build won't take the base-URL override, probe_eligible() returns False and it
lands in the unmatched appendix.
"""

from __future__ import annotations

import json
import shutil

from harnessbench.adapters.base import Adapter
from harnessbench.config import Task


class CodexAdapter(Adapter):
    name = "codex"

    def env(self, run_id: str) -> dict[str, str]:
        e = super().env(run_id)
        e.update(
            {
                # LiteLLM proxy speaks OpenAI-compatible on this base.
                "OPENAI_BASE_URL": self.proxy_base_url,
                "OPENAI_API_KEY": self.proxy_key,
            }
        )
        return e

    def build_cmd(self, task: Task, run_id: str) -> list[str]:
        return [
            "codex",
            "exec",
            task.prompt,
            "--model",
            self.suite.bench_model_name,
            "--dangerously-bypass-approvals-and-sandbox",
        ]

    def parse_native_usage(self, stdout: str, stderr: str) -> int | None:
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            usage = obj.get("usage") or {}
            if isinstance(usage, dict) and usage:
                return int(usage.get("total_tokens", 0)) or None
        return None

    def probe_eligible(self) -> bool:
        # Not installed on this host, and base-URL override is version-dependent.
        return shutil.which("codex") is not None
