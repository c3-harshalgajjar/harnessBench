"""The runner: orchestrate proxy + per-(task x harness x trial) dispatch, then score.

Flow:
    1. Start the LiteLLM proxy (pins model + thinking, logs authoritative usage).
    2. For each task x eligible harness x trial:
        a. Copy the task workspace into a fresh scratch dir (/work for the container).
        b. Dispatch the harness (in-container; Bob runs on host).
        c. Read proxy telemetry for this run_id -> tokens + parity assertion.
        d. Run hidden tests against the post-run workspace -> passed.
        e. Emit one RunResult row to runs.jsonl.
    3. Stop the proxy.

Only eligible harnesses are dispatched into the scored path. Ineligible harnesses
(e.g. cursor) are recorded as skipped rows for the unmatched appendix.
"""

from __future__ import annotations

import secrets
import shutil
import tempfile
from pathlib import Path

from harnessbench.adapters import get_adapter
from harnessbench.config import RunResult, Suite, Task
from harnessbench.docker_run import run_in_container
from harnessbench.proxy_manager import Proxy
from harnessbench.scoring import run_hidden_tests
from harnessbench.telemetry import aggregate


def _copy_workspace(task: Task, dest_parent: Path) -> Path:
    work = dest_parent / "work"
    if task.workspace_dir.exists():
        shutil.copytree(task.workspace_dir, work)
    else:
        work.mkdir(parents=True)
    return work


class Runner:
    def __init__(
        self,
        suite: Suite,
        tasks: dict[str, Task],
        out_dir: Path,
        image: str = "harnessbench-base:latest",
        proxy_port: int = 4000,
    ):
        self.suite = suite
        self.tasks = tasks
        self.out_dir = out_dir
        self.image = image
        self.proxy_port = proxy_port
        self.proxy_key = "sk-harnessbench-" + secrets.token_hex(8)
        self.usage_log = out_dir / "usage.jsonl"
        self.runs_log = out_dir / "runs.jsonl"

    def _selected_tasks(self) -> list[Task]:
        if self.suite.task_ids:
            return [self.tasks[t] for t in self.suite.task_ids if t in self.tasks]
        return list(self.tasks.values())

    def run(self) -> list[RunResult]:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        # Truncate logs for a clean run.
        self.usage_log.write_text("")
        results: list[RunResult] = []

        with Proxy(self.proxy_port, self.usage_log, self.proxy_key):
            proxy_base_container = f"http://host.docker.internal:{self.proxy_port}"
            for task in self._selected_tasks():
                for h in self.suite.harnesses:
                    adapter = get_adapter(
                        h.adapter, self.suite, proxy_base_container, self.proxy_key
                    )
                    if not h.eligible or not adapter.probe_eligible():
                        results.append(
                            self._skipped_row(task, h.name, "ineligible-no-parity")
                        )
                        continue
                    for trial in range(self.suite.trials):
                        results.append(self._one_run(task, h.name, adapter, trial))

        with self.runs_log.open("w") as fh:
            for r in results:
                fh.write(r.model_dump_json() + "\n")
        return results

    def _one_run(self, task: Task, harness: str, adapter, trial: int) -> RunResult:
        run_id = f"{task.id}__{harness}__t{trial}__{secrets.token_hex(4)}"
        with tempfile.TemporaryDirectory(prefix="hb-") as tmp:
            work = _copy_workspace(task, Path(tmp))
            stdout, stderr, wall, timed_out = run_in_container(
                adapter, task, run_id, self.image, work, self.proxy_key
            )
            native = adapter.parse_native_usage(stdout, stderr)
            passed, _test_out = (False, "")
            if not timed_out:
                passed, _test_out = run_hidden_tests(
                    work, task.tests_dir, self.image
                )

        tele = aggregate(self.usage_log).get(run_id)
        parity_ok = (
            tele.parity_ok(self.suite.pinned_model, self.suite.thinking_budget_tokens)
            if tele
            else False
        )
        return RunResult(
            run_id=run_id,
            task_id=task.id,
            category=task.category,
            difficulty=task.difficulty,
            harness=harness,
            trial=trial,
            resolved_model=next(iter(tele.resolved_models)) if tele and tele.resolved_models else None,
            resolved_thinking_budget=(
                next(iter(tele.resolved_budgets)) if tele and tele.resolved_budgets else None
            ),
            model_parity_ok=parity_ok,
            passed=passed,
            timed_out=timed_out,
            wall_seconds=round(wall, 2),
            total_tokens=tele.total_tokens if tele else 0,
            input_tokens=tele.input_tokens if tele else 0,
            output_tokens=tele.output_tokens if tele else 0,
            cache_read_tokens=tele.cache_read_tokens if tele else 0,
            cache_write_tokens=tele.cache_write_tokens if tele else 0,
            num_requests=tele.num_requests if tele else 0,
            native_total_tokens=native,
        )

    def _skipped_row(self, task: Task, harness: str, reason: str) -> RunResult:
        return RunResult(
            run_id=f"{task.id}__{harness}__skipped",
            task_id=task.id,
            category=task.category,
            difficulty=task.difficulty,
            harness=harness,
            trial=-1,
            model_parity_ok=False,
            error=reason,
        )
