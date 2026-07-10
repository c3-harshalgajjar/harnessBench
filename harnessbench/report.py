"""Leaderboard: fold runs.jsonl into per-harness aggregates and render markdown.

Two tiers, always separated:
    - SCORED: runs with model_parity_ok=True. These are the only rows that produce
      leaderboard numbers, because model + thinking were provably identical.
    - UNMATCHED APPENDIX: ineligible/parity-failed harnesses, listed for context but
      never ranked against the scored tier.

Per scored harness we report: pass rate, median wall seconds, median total tokens,
tokens-per-pass (efficiency), and cache-read ratio. Ranking key is tokens-per-pass
(lower is better) among harnesses with comparable pass rates.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from harnessbench.config import RunResult


@dataclass
class HarnessAgg:
    harness: str
    passes: int = 0
    total: int = 0
    wall: list[float] = field(default_factory=list)
    tokens: list[int] = field(default_factory=list)
    cache_read: list[int] = field(default_factory=list)
    input_tokens: list[int] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.passes / self.total if self.total else 0.0

    @property
    def median_wall(self) -> float:
        return statistics.median(self.wall) if self.wall else 0.0

    @property
    def median_tokens(self) -> int:
        return int(statistics.median(self.tokens)) if self.tokens else 0

    @property
    def tokens_per_pass(self) -> float:
        return (sum(self.tokens) / self.passes) if self.passes else float("inf")

    @property
    def cache_ratio(self) -> float:
        tot_in = sum(self.input_tokens) + sum(self.cache_read)
        return (sum(self.cache_read) / tot_in) if tot_in else 0.0


def _load(runs_log: Path) -> list[RunResult]:
    rows = []
    for line in runs_log.read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(RunResult(**json.loads(line)))
    return rows


def build_report(runs_log: Path) -> str:
    rows = _load(runs_log)
    scored: dict[str, HarnessAgg] = defaultdict(lambda: HarnessAgg(""))
    unmatched: set[str] = set()

    for r in rows:
        if r.trial < 0 or not r.model_parity_ok:
            unmatched.add(r.harness)
            continue
        a = scored[r.harness]
        a.harness = r.harness
        a.total += 1
        if r.passed:
            a.passes += 1
        a.wall.append(r.wall_seconds)
        a.tokens.append(r.total_tokens)
        a.cache_read.append(r.cache_read_tokens)
        a.input_tokens.append(r.input_tokens)

    ranked = sorted(
        scored.values(),
        key=lambda a: (-round(a.pass_rate, 2), a.tokens_per_pass),
    )

    lines = ["# Harness Benchmark — Leaderboard", ""]
    lines.append(
        "All scored harnesses ran the **same pinned model at the same thinking "
        "budget** (enforced server-side by the proxy). Rows below are directly "
        "comparable."
    )
    lines.append("")
    lines.append(
        "| Rank | Harness | Pass rate | Median wall (s) | Median tokens | "
        "Tokens/pass | Cache-read ratio |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for i, a in enumerate(ranked, 1):
        tpp = "—" if a.tokens_per_pass == float("inf") else f"{a.tokens_per_pass:,.0f}"
        lines.append(
            f"| {i} | **{a.harness}** | {a.pass_rate:.0%} | {a.median_wall:.1f} | "
            f"{a.median_tokens:,} | {tpp} | {a.cache_ratio:.0%} |"
        )

    if unmatched:
        lines += [
            "",
            "## Unmatched appendix (not scored)",
            "",
            "These harnesses could not be pinned to the benchmark model+thinking "
            "budget (they route through their own gateway), so their runs are "
            "**excluded from the leaderboard**. Listed for reference only:",
            "",
        ]
        for h in sorted(unmatched):
            lines.append(f"- `{h}`")

    lines.append("")
    return "\n".join(lines)
