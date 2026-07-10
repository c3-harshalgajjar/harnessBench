"""Bob adapter — runs on the HOST, not in-container.

Bob is a multi-agent orchestrator that shells out to an inner runtime (claude /
cursor / local). To keep parity, Bob's inner runtime is itself pointed at the proxy
via ANTHROPIC_BASE_URL, and the inner harness is pinned to `bench-model`. We record
which inner harness was used (inner_harness on RunResult) so Bob rows are comparable
only within the same inner runtime.

Because Bob mutates local state and expects its own repo layout, it runs on the host
against a throwaway copy of the task workspace rather than inside the base image.
Dispatch: `bob --auto --yes -m <prompt>` with steering neutralized by the runner.
"""

from __future__ import annotations

from harnessbench.adapters.base import Adapter
from harnessbench.config import Task


class BobAdapter(Adapter):
    name = "bob"

    def env(self, run_id: str) -> dict[str, str]:
        e = super().env(run_id)
        e.update(
            {
                "ANTHROPIC_BASE_URL": self.proxy_base_url,
                "ANTHROPIC_AUTH_TOKEN": self.proxy_key,
                "BOB_RUNTIME": "claude",  # inner runtime; recorded as inner_harness
            }
        )
        return e

    def build_cmd(self, task: Task, run_id: str) -> list[str]:
        return [
            "bob",
            "--auto",
            "--yes",
            "-m",
            task.prompt,
        ]

    def probe_eligible(self) -> bool:
        # Scored only within its inner-runtime cohort; the proxy still measures it.
        return True
