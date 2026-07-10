#!/usr/bin/env bash
# Hidden test for context-fill-ledger-audit. Passes iff balances.json in /work
# exactly matches the ground-truth net balances derived from the module files.
# The reference is committed alongside the workspace (both produced by gen.py
# from the same seed), and mounted read-only at /tests/balances.json.
set -uo pipefail

cd /work || { echo "FAIL: no /work"; exit 1; }

if [[ ! -f balances.json ]]; then
  echo "FAIL: balances.json missing"
  exit 1
fi

python3 - <<'PY'
import json, sys

try:
    got = json.load(open("/work/balances.json"))
except Exception as e:
    print(f"FAIL: balances.json not valid JSON: {e}")
    sys.exit(1)

expected = json.load(open("/tests/balances.json"))

if not isinstance(got, dict):
    print("FAIL: balances.json is not a JSON object")
    sys.exit(1)

# Normalize: ints, drop nothing, exact key+value match.
try:
    got_norm = {str(k): int(v) for k, v in got.items()}
except Exception as e:
    print(f"FAIL: non-integer balance value: {e}")
    sys.exit(1)

exp_norm = {str(k): int(v) for k, v in expected.items()}

missing = set(exp_norm) - set(got_norm)
extra = set(got_norm) - set(exp_norm)
if missing:
    print(f"FAIL: missing IDs: {sorted(missing)}")
    sys.exit(1)
if extra:
    print(f"FAIL: unexpected IDs: {sorted(extra)}")
    sys.exit(1)

wrong = {k: (got_norm[k], exp_norm[k]) for k in exp_norm if got_norm[k] != exp_norm[k]}
if wrong:
    print(f"FAIL: wrong balances (got, expected): {wrong}")
    sys.exit(1)

print(f"PASS: all {len(exp_norm)} balances correct")
PY
exit $?
