#!/usr/bin/env bash
# Hidden test for react-cart-total-bug. Runs in the base image, cwd=/work (the
# harness-modified workspace), with /tests mounted read-only. Exits 0 iff the
# fix is correct.
#
# We copy the hidden spec into the workspace, install deps, and run vitest against
# it. The harness never saw this spec, so it can't overfit to it.
set -uo pipefail

cp /tests/hidden.test.jsx /work/src/hidden.test.jsx

# Deps: the harness may or may not have installed them. Install if missing.
if [[ ! -d /work/node_modules ]]; then
  echo "[run.sh] node_modules missing, installing..."
  npm install --no-audit --no-fund --loglevel=error || { echo "npm install failed"; exit 1; }
fi

npx vitest run src/hidden.test.jsx
code=$?

rm -f /work/src/hidden.test.jsx
exit $code
