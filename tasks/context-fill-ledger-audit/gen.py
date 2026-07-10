#!/usr/bin/env python3
"""Deterministic generator for the context-fill-ledger-audit task.

Produces:
  - workspace/modules/mod_000.txt .. mod_(N-1).txt  (the synthetic codebase)
  - reference/balances.json                          (ground-truth answer)

Both are a pure function of SEED + N + IDS below, so the fixture and grader
can never drift. Re-run this script to regenerate; the output is committed so
the runner can mount workspace/ directly without a build step.

Run from the task directory:
    python3 gen.py
"""
from __future__ import annotations

import json
import random
from pathlib import Path

SEED = 20260710
N_FILES = 400
LINES_PER_FILE = 40
# Ledger IDs in play. Net balances are whatever the random walk produces; the
# reference is computed from the same stream, so it's authoritative regardless.
N_IDS = 18
OPS = ("CREDIT", "DEBIT")


def main() -> None:
    here = Path(__file__).resolve().parent
    modules = here / "workspace" / "modules"
    modules.mkdir(parents=True, exist_ok=True)
    reference = here / "reference"
    reference.mkdir(parents=True, exist_ok=True)

    rng = random.Random(SEED)
    ids = [f"LG-{i:04d}" for i in range(1, N_IDS + 1)]
    balances: dict[str, int] = {}
    seen: set[str] = set()

    # Guarantee every id appears at least once, and that some entries land in the
    # very first files (the ones a naive harness evicts first under compaction).
    forced_positions = {i: rng.randrange(0, 12) for i in range(N_IDS)}

    for f in range(N_FILES):
        lines: list[str] = []
        lines.append(f"# module {f:03d}")
        lines.append(f"MODULE_{f:03d}_CODE = \"{rng.randrange(10**6, 10**7)}\"")
        for _ln in range(LINES_PER_FILE):
            roll = rng.random()
            if roll < 0.22:
                lid = rng.choice(ids)
                op = rng.choice(OPS)
                amount = rng.randrange(1, 5000)
                lines.append(f"LEDGER {lid} {op} {amount}")
                delta = amount if op == "CREDIT" else -amount
                balances[lid] = balances.get(lid, 0) + delta
                seen.add(lid)
            else:
                # noise: plausible-looking constants to bulk up context
                lines.append(
                    f"CONST_{rng.randrange(0, 999):03d} = "
                    f"{rng.randrange(0, 10**9)}"
                )
        # Force any id whose "early appearance" slot is this file.
        for idx, pos in forced_positions.items():
            if pos == f:
                lid = ids[idx]
                op = rng.choice(OPS)
                amount = rng.randrange(1, 5000)
                lines.append(f"LEDGER {lid} {op} {amount}")
                delta = amount if op == "CREDIT" else -amount
                balances[lid] = balances.get(lid, 0) + delta
                seen.add(lid)
        (modules / f"mod_{f:03d}.txt").write_text("\n".join(lines) + "\n")

    final = {lid: balances[lid] for lid in sorted(seen)}
    answer = json.dumps(final, indent=2) + "\n"
    # reference/ is for human inspection; tests/ is what the grader reads
    # read-only inside the container. Both come from this one computation so
    # they can't drift.
    (reference / "balances.json").write_text(answer)
    tests = here / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    (tests / "balances.json").write_text(answer)
    print(f"wrote {N_FILES} files, {len(final)} ledger IDs -> reference/ + tests/ balances.json")


if __name__ == "__main__":
    main()
