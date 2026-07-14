"""Container dispatch: run one harness invocation in the base image against a fresh
copy of the task workspace, with steering neutralized and the proxy reachable.

The heavy lifting of steering sanitization + MCP config generation lives in the
image's entrypoint.sh; here we just assemble the `docker run` invocation, inject the
adapter's env + argv, and capture stdout/stderr + wall time.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from harnessbench.adapters.base import Adapter
from harnessbench.config import McpServerSpec, Task


def _mcp_json(mcp: list[McpServerSpec]) -> str:
    """Claude-style mcpServers config the entrypoint drops at /harnessbench/mcp.json."""
    return json.dumps(
        {
            "mcpServers": {
                s.name: {"command": s.command, "args": s.args} for s in mcp
            }
        }
    )


def run_in_container(
    adapter: Adapter,
    task: Task,
    run_id: str,
    image: str,
    work_copy: Path,
    proxy_key: str,
) -> tuple[str, str, float, bool]:
    """Return (stdout, stderr, wall_seconds, timed_out)."""
    env = adapter.env(run_id)
    argv = adapter.build_cmd(task, run_id)

    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "--add-host",
        "host.docker.internal:host-gateway",
        "-v",
        f"{work_copy}:/work",
        "-w",
        "/work",
    ]
    for k, v in env.items():
        docker_cmd += ["-e", f"{k}={v}"]
    docker_cmd += ["-e", f"HARNESSBENCH_MCP_JSON={_mcp_json(task.mcp)}"]
    docker_cmd += [image] + argv

    start = time.time()
    timed_out = False
    try:
        proc = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=task.timeout_seconds,
        )
        stdout, stderr = proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        timed_out = True
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
    wall = time.time() - start
    return stdout, stderr, wall, timed_out


def run_on_host(
    adapter: Adapter,
    task: Task,
    run_id: str,
    work_copy: Path,
) -> tuple[str, str, float, bool]:
    """Run the adapter's DIRECT-mode argv on the host, inheriting host env (so a
    harness's own subscription auth — e.g. Claude Code's Keychain OAuth — works).

    Mirrors run_in_container's return contract: (stdout, stderr, wall, timed_out).
    """
    import os

    argv = adapter.build_cmd_direct(task, run_id)
    env = {**os.environ, **adapter.env_direct(run_id)}
    # Materialize MCP config in the workspace so `--mcp-config mcp.json` resolves
    # relative to cwd. Server command/args run on the host, from work_copy.
    if task.mcp:
        (work_copy / "mcp.json").write_text(_mcp_json(task.mcp))

    start = time.time()
    timed_out = False
    try:
        proc = subprocess.run(
            argv,
            cwd=str(work_copy),
            env=env,
            capture_output=True,
            text=True,
            timeout=task.timeout_seconds,
        )
        stdout, stderr = proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        timed_out = True
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
    wall = time.time() - start
    return stdout, stderr, wall, timed_out
