"""Leaderboard: fold runs.jsonl into per-harness aggregates and render markdown.

Three tiers, always separated — the report NEVER ranks across them:
    - PROXY-VERIFIED (scored): run_mode="proxied" AND model_parity_ok=True. The only
      rows that produce a ranked leaderboard, because model + thinking were provably
      identical (pinned server-side) and tokens are proxy-authoritative.
    - SELF-REPORTED (unverified): run_mode="direct". Ran on the host with the harness's
      own subscription auth; nothing pinned; tokens are the harness's self-report.
      Shown for reference — pass/fail and wall-time are honest, tokens are not
      comparable to the verified tier.
    - APPENDIX (skipped): ineligible or no native host auth. Listed, never measured.

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

    def add(self, r: RunResult) -> None:
        self.harness = r.harness
        self.total += 1
        if r.passed:
            self.passes += 1
        self.wall.append(r.wall_seconds)
        self.tokens.append(r.total_tokens)
        self.cache_read.append(r.cache_read_tokens)
        self.input_tokens.append(r.input_tokens)


def _load(runs_log: Path) -> list[RunResult]:
    rows = []
    for line in runs_log.read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(RunResult(**json.loads(line)))
    return rows


def _ranked_table(aggs: dict[str, HarnessAgg], with_tokens: bool) -> list[str]:
    ranked = sorted(
        aggs.values(),
        key=lambda a: (-round(a.pass_rate, 2), a.tokens_per_pass),
    )
    lines: list[str] = []
    if with_tokens:
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
    else:
        # Self-reported tier: pass/fail + wall are honest, tokens are the harness's own
        # number (flagged), so show them but don't imply they're comparable.
        lines.append(
            "| Harness | Pass rate | Median wall (s) | Median tokens (self-reported) |"
        )
        lines.append("|---|---|---|---|")
        for a in ranked:
            lines.append(
                f"| **{a.harness}** | {a.pass_rate:.0%} | {a.median_wall:.1f} | "
                f"{a.median_tokens:,} |"
            )
    return lines


def build_report(runs_log: Path) -> str:
    rows = _load(runs_log)
    scored: dict[str, HarnessAgg] = defaultdict(lambda: HarnessAgg(""))
    self_reported: dict[str, HarnessAgg] = defaultdict(lambda: HarnessAgg(""))
    appendix: set[str] = set()

    for r in rows:
        if r.trial < 0:
            appendix.add(r.harness)
        elif r.run_mode == "proxied" and r.model_parity_ok:
            scored[r.harness].add(r)
        elif r.run_mode == "direct":
            self_reported[r.harness].add(r)
        else:
            appendix.add(r.harness)

    lines = ["# Harness Benchmark — Leaderboard", ""]

    if scored:
        lines += [
            "## Proxy-verified (scored)",
            "",
            "All harnesses below ran the **same pinned model at the same thinking "
            "budget** (enforced server-side by the proxy) and their tokens are "
            "proxy-authoritative. These rows are directly comparable.",
            "",
        ]
        lines += _ranked_table(scored, with_tokens=True)
        lines.append("")

    if self_reported:
        lines += [
            "## Self-reported (unverified — no API key)",
            "",
            "These ran on the host with the harness's own subscription auth. **No model "
            "or thinking-budget pinning**, and token counts are the harness's own "
            "self-report — not comparable to the verified tier above. Pass/fail and "
            "wall-time are honest; use tokens as a rough intra-harness signal only.",
            "",
        ]
        lines += _ranked_table(self_reported, with_tokens=False)
        lines.append("")

    if appendix:
        lines += [
            "## Appendix (not measured)",
            "",
            "Skipped — either ineligible (routes through its own gateway, can't be "
            "pinned) or lacks native host auth in the no-key path. Listed for reference "
            "only:",
            "",
        ]
        for h in sorted(appendix):
            lines.append(f"- `{h}`")
        lines.append("")

    if not (scored or self_reported):
        lines += ["_No runnable harnesses produced results._", ""]

    return "\n".join(lines)
