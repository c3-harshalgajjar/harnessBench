"""Task discovery: load task.yaml specs from the tasks/ tree.

Layout per task:
    tasks/<category>/<task_id>/
        task.yaml          # Task fields (id, category, difficulty, prompt, ...)
        workspace/         # starting files copied fresh into each run's /work
        tests/run.sh       # hidden deterministic scorer, exits 0 iff passed
        reference/         # reference solution (never mounted into a run)
"""

from __future__ import annotations

from pathlib import Path

from harnessbench.config import Task

TASKS_ROOT = Path(__file__).resolve().parent.parent / "tasks"


def discover_tasks(root: Path | None = None) -> dict[str, Task]:
    root = root or TASKS_ROOT
    out: dict[str, Task] = {}
    for task_yaml in sorted(root.glob("*/*/task.yaml")):
        task = Task.load(task_yaml.parent)
        out[task.id] = task
    return out
