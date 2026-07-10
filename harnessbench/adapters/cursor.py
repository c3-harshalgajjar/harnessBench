"""Cursor CLI (cursor-agent) adapter — UNSCORED by default.

Cursor's hosted models route through Cursor's own gateway and bake the thinking
preset into the model name; there's no documented base-URL override to force traffic
through our proxy. That breaks model+thinking parity, so this harness is
`eligible=False` in the suite config and appears only in the unmatched appendix
(its own tokens are self-reported, not proxy-measured).

The adapter is kept so the appendix can still record wall-time and pass/fail for a
qualitative, non-scored data point.
"""

from __future__ import annotations

from harnessbench.adapters.base import Adapter
from harnessbench.config import Task


class CursorAdapter(Adapter):
    name = "cursor"

    def build_cmd(self, task: Task, run_id: str) -> list[str]:
        return [
            "cursor-agent",
            "-p",
            task.prompt,
            "--output-format",
            "json",
            "--force",
        ]

    def probe_eligible(self) -> bool:
        # No base-URL override => cannot enforce parity => never scored.
        return False
