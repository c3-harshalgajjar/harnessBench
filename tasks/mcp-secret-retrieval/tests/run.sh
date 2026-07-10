#!/usr/bin/env bash
# Hidden test for mcp-secret-retrieval. Passes iff RELEASE_TOKEN.txt contains the
# exact token the MCP tool returns. The token is only obtainable by calling the
# tool, so a pass proves the harness exercised the MCP server.
set -uo pipefail

EXPECTED="rlz_7Q2m9Xbe4KpN"
FILE=/work/RELEASE_TOKEN.txt

if [[ ! -f "$FILE" ]]; then
  echo "FAIL: $FILE does not exist"
  exit 1
fi

GOT="$(tr -d '[:space:]' < "$FILE")"
if [[ "$GOT" == "$EXPECTED" ]]; then
  echo "PASS: token matches"
  exit 0
fi
echo "FAIL: expected '$EXPECTED', got '$GOT'"
exit 1
