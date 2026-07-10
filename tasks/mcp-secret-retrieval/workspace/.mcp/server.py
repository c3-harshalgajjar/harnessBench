#!/usr/bin/env python3
"""Minimal deterministic stdio MCP server for the mcp-secret-retrieval task.

Speaks just enough of the Model Context Protocol (JSON-RPC 2.0 over stdio) for a
coding-agent harness to discover and call one tool, `get_release_token`, which
returns a fixed token. Deterministic on purpose: the grader checks for this exact
value, so a passing run PROVES the harness actually invoked the MCP tool rather
than guessing.

No third-party deps — harnesses run this with the container's stock python3.
"""

import json
import sys

RELEASE_TOKEN = "rlz_7Q2m9Xbe4KpN"  # nosec - fixed benchmark fixture, not a secret

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "get_release_token",
        "description": "Return the current release token for this deployment.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    }
]


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _result(req_id, result) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _handle(msg: dict) -> None:
    method = msg.get("method")
    req_id = msg.get("id")

    if method == "initialize":
        _result(
            req_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "vault", "version": "1.0.0"},
            },
        )
    elif method == "notifications/initialized":
        pass  # notification, no response
    elif method == "tools/list":
        _result(req_id, {"tools": TOOLS})
    elif method == "tools/call":
        params = msg.get("params") or {}
        if params.get("name") == "get_release_token":
            _result(
                req_id,
                {"content": [{"type": "text", "text": RELEASE_TOKEN}], "isError": False},
            )
        else:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": "unknown tool"},
                }
            )
    elif method == "ping":
        _result(req_id, {})
    elif req_id is not None:
        _send(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"method not found: {method}"},
            }
        )


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        _handle(msg)


if __name__ == "__main__":
    main()
