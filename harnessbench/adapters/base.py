"""Adapter ABC. One subclass per harness normalizes invocation + usage parsing.

An adapter's job is narrow:
  - build_cmd(): the headless command line to run the harness in-container
  - env():       env vars that point the harness at our proxy (base URL + dummy key)
                 and hand it the bench-model name + run_id header
  - parse_native_usage(): best-effort token count from the harness's own output,
                 used ONLY as a divergence cross-check against the proxy truth
  - probe_eligible(): can this harness be pointed at an arbitrary base URL? If not,
                 it's excluded from the scored tier.

Adapters never pick the real model or thinking budget — the proxy does.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from harnessbench.config import Suite, Task


class Adapter(ABC):
    name: str = "base"

    def __init__(self, suite: Suite, proxy_base_url: str, proxy_key: str):
        self.suite = suite
        self.proxy_base_url = proxy_base_url
        self.proxy_key = proxy_key

    @abstractmethod
    def build_cmd(self, task: Task, run_id: str) -> list[str]:
        """Return argv for the harness's headless invocation."""

    def env(self, run_id: str) -> dict[str, str]:
        """Base env shared by most harnesses. Subclasses extend/override.

        The run_id also travels as an env var so the proxy callback can attribute
        usage even when a harness strips custom headers.
        """
        return {
            "HARNESSBENCH_RUN_ID": run_id,
            "HARNESSBENCH_PROXY_KEY": self.proxy_key,
        }

    def parse_native_usage(self, stdout: str, stderr: str) -> int | None:
        """Best-effort native token total for cross-check. None if unavailable."""
        return None

    def build_cmd_direct(self, task: Task, run_id: str) -> list[str]:
        """argv for running WITHOUT the proxy (no-key / direct mode).

        Defaults to the proxied argv; adapters override when direct mode needs a
        different model alias or flags (e.g. Claude Code can't say `bench-model`
        when there's no proxy to rewrite it).
        """
        return self.build_cmd(task, run_id)

    def env_direct(self, run_id: str) -> dict[str, str]:
        """Env for direct mode. Defaults to empty so the harness uses its own
        native (subscription) auth — no proxy base-URL override."""
        return {}

    @abstractmethod
    def probe_eligible(self) -> bool:
        """True if this harness accepts our proxy base URL (scored-tier gate)."""

    # Shared header the proxy reads to attribute usage to a run.
    def run_id_header(self, run_id: str) -> dict[str, str]:
        return {"x-harnessbench-run-id": run_id}
