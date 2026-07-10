"""Telemetry: read the proxy usage JSONL and produce authoritative per-run token
totals + the model-parity verdict.

The proxy writes one row per request tagged with run_id. We aggregate by run_id and
assert every row resolved to the pinned model + thinking budget. If any row diverges,
model_parity_ok=False and the run is dropped from scoring by the runner.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RunTelemetry:
    run_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    num_requests: int = 0
    resolved_models: set[str] = field(default_factory=set)
    resolved_budgets: set[int | None] = field(default_factory=set)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def parity_ok(self, pinned_model: str, pinned_budget: int) -> bool:
        # Every resolved model must contain the pinned model id (litellm may prefix
        # the provider), and every budget must equal the pin.
        if not self.resolved_models:
            return False
        model_ok = all(
            pinned_model.split("/")[-1] in (m or "") for m in self.resolved_models
        )
        budget_ok = all(
            (b is None or int(b) == pinned_budget) for b in self.resolved_budgets
        )
        return model_ok and budget_ok


def aggregate(usage_log: Path) -> dict[str, RunTelemetry]:
    """Fold the JSONL into per-run telemetry keyed by run_id."""
    out: dict[str, RunTelemetry] = {}
    if not usage_log.exists():
        return out
    for line in usage_log.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = row.get("run_id", "unknown")
        t = out.setdefault(rid, RunTelemetry(run_id=rid))
        t.input_tokens += int(row.get("prompt_tokens", 0))
        t.output_tokens += int(row.get("completion_tokens", 0))
        t.cache_read_tokens += int(row.get("cache_read_tokens", 0))
        t.cache_write_tokens += int(row.get("cache_write_tokens", 0))
        t.num_requests += 1
        if row.get("resolved_model"):
            t.resolved_models.add(row["resolved_model"])
        t.resolved_budgets.add(row.get("resolved_thinking_budget"))
    return out
