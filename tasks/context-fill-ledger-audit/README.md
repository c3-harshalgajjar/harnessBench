# context-fill-ledger-audit

High-difficulty compaction probe. A large synthetic codebase (400 module files)
with `LEDGER` entries scattered throughout — including the earliest files a naive
harness evicts first under compaction. The harness must find every entry and
compute the net balance per ID.

## Materialize the workspace (required before running)

The workspace and ground-truth answer are **not committed** — they are generated
deterministically from a fixed seed, so the fixture and grader can never drift.
Generate them with one command:

```bash
python3 gen.py
```

This writes:

- `workspace/modules/mod_000.txt … mod_399.txt` — the synthetic codebase.
- `reference/balances.json` — ground-truth answer (human inspection).
- `tests/balances.json` — the same answer, mounted read-only for the grader.

Re-running `gen.py` is idempotent. The output is a pure function of `SEED`,
`N_FILES`, and `N_IDS` at the top of the script.
