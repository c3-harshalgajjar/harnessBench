"""Scoring: run a task's hidden tests against the harness-modified workspace.

Each task ships a `tests/` dir with a `run.sh` that exits 0 iff the task passed. We
copy the harness's post-run workspace, mount the hidden tests read-only over it, and
run `tests/run.sh` in the same base image. Deterministic — no LLM-as-judge.

For context-fill tasks, run.sh additionally checks the post-compaction assertion
(the task's final requirement can only be satisfied if early context survived
compaction), which populates post_compaction_passed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_hidden_tests(
    workspace: Path,
    tests_dir: Path,
    image: str,
    timeout: int = 600,
) -> tuple[bool, str]:
    """Return (passed, combined_output). Runs tests/run.sh inside the base image."""
    run_sh = tests_dir / "run.sh"
    if not run_sh.exists():
        return False, f"no tests/run.sh in {tests_dir}"

    cmd = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",  # tests are hermetic
        "-v",
        f"{workspace}:/work",
        "-v",
        f"{tests_dir}:/tests:ro",
        "-w",
        "/work",
        image,
        "bash",
        "/tests/run.sh",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "hidden-test timeout"
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, output
