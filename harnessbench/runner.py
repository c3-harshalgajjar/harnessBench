"""The runner: orchestrate proxy + per-(task x harness x trial) dispatch, then score.

Two modes, chosen by ANTHROPIC_API_KEY presence:

Mode A — proxied (key present):
    1. Start the LiteLLM proxy (pins model + thinking, logs authoritative usage).
    2. For each task x eligible harness x trial: copy workspace, dispatch in-container,
       read proxy telemetry -> tokens + parity, run hidden tests, emit a RunResult.
    3. Stop the proxy. Rows are tokens_verified=True, run_mode="proxied".

Mode B — direct (no key):
    No proxy. A harness runs only if it opts into host execution for the no-key path
    (run_on_host_when_no_key) or is always-host (run_on_host) AND can auth natively on
    the host. It runs on the host with its own subscription auth; tokens come from the
    harness's self-report (tokens_verified=False, model_parity_ok=False,
    run_mode="direct"). Hidden tests still run hermetically in-container. Harnesses with
    no native host auth are recorded as skipped.

Ineligible harnesses (e.g. cursor) are always recorded as skipped rows.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import shutil
import tempfile
from pathlib import Path

from harnessbench.adapters import get_adapter
from harnessbench.config import Harness, RunResult, Suite, Task
from harnessbench.docker_run import run_in_container, run_on_host
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
        # Proxy (and thus the scored path) is only possible with a provider key.
        self.proxied = bool(os.environ.get("ANTHROPIC_API_KEY"))

    def _selected_tasks(self) -> list[Task]:
        if self.suite.task_ids:
            return [self.tasks[t] for t in self.suite.task_ids if t in self.tasks]
        return list(self.tasks.values())

    def run(self) -> list[RunResult]:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.usage_log.write_text("")
        results: list[RunResult] = []

        if self.proxied:
            proxy_cm = Proxy(self.proxy_port, self.usage_log, self.proxy_key)
            proxy_base = f"http://host.docker.internal:{self.proxy_port}"
        else:
            proxy_cm = contextlib.nullcontext()
            proxy_base = ""

        with proxy_cm:
            for task in self._selected_tasks():
                for h in self.suite.harnesses:
                    adapter = get_adapter(
                        h.adapter, self.suite, proxy_base, self.proxy_key
                    )
                    if self.proxied:
                        results.extend(self._run_proxied(task, h, adapter))
                    else:
                        results.extend(self._run_direct(task, h, adapter))

        with self.runs_log.open("w") as fh:
            for r in results:
                fh.write(r.model_dump_json() + "\n")
        return results

    # -- Mode A: proxied -----------------------------------------------------

    def _run_proxied(
        self, task: Task, h: Harness, adapter
    ) -> list[RunResult]:
        if not h.eligible or not adapter.probe_eligible():
            return [self._skipped_row(task, h.name, "ineligible-no-parity")]
        return [
            self._one_proxied(task, h.name, adapter, trial)
            for trial in range(self.suite.trials)
        ]

    def _one_proxied(self, task: Task, harness: str, adapter, trial: int) -> RunResult:
        run_id = f"{task.id}__{harness}__t{trial}__{secrets.token_hex(4)}"
        with tempfile.TemporaryDirectory(prefix="hb-") as tmp:
            work = _copy_workspace(task, Path(tmp))
            stdout, stderr, wall, timed_out = run_in_container(
                adapter, task, run_id, self.image, work, self.proxy_key
            )
            native = adapter.parse_native_usage(stdout, stderr)
            passed = False
            if not timed_out:
                passed, _ = run_hidden_tests(work, task.tests_dir, self.image)

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
            run_mode="proxied",
            tokens_verified=True,
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

    # -- Mode B: direct (no key) --------------------------------------------

    def _run_direct(self, task: Task, h: Harness, adapter) -> list[RunResult]:
        if not h.eligible:
            return [self._skipped_row(task, h.name, "ineligible")]
        # Direct mode only runs harnesses that execute on the host with their own auth.
        if not (h.run_on_host or h.run_on_host_when_no_key):
            return [
                self._skipped_row(
                    task, h.name, "skipped: no native host auth in direct mode"
                )
            ]
        return [
            self._one_direct(task, h.name, adapter, trial)
            for trial in range(self.suite.trials)
        ]

    def _one_direct(self, task: Task, harness: str, adapter, trial: int) -> RunResult:
        run_id = f"{task.id}__{harness}__t{trial}__{secrets.token_hex(4)}"
        split = None
        with tempfile.TemporaryDirectory(prefix="hb-") as tmp:
            work = _copy_workspace(task, Path(tmp))
            stdout, stderr, wall, timed_out = run_on_host(adapter, task, run_id, work)
            native = adapter.parse_native_usage(stdout, stderr)
            # Prefer the split breakdown when the adapter exposes it (Claude does).
            if hasattr(adapter, "parse_usage_split"):
                split = adapter.parse_usage_split(stdout)
            passed = False
            if not timed_out:
                passed, _ = run_hidden_tests(work, task.tests_dir, self.image)

        total = (split or {}).get("total_tokens", native or 0)
        return RunResult(
            run_id=run_id,
            task_id=task.id,
            category=task.category,
            difficulty=task.difficulty,
            harness=harness,
            trial=trial,
            run_mode="direct",
            tokens_verified=False,
            model_parity_ok=False,
            passed=passed,
            timed_out=timed_out,
            wall_seconds=round(wall, 2),
            total_tokens=total,
            input_tokens=(split or {}).get("input_tokens", 0),
            output_tokens=(split or {}).get("output_tokens", 0),
            cache_read_tokens=(split or {}).get("cache_read_tokens", 0),
            cache_write_tokens=(split or {}).get("cache_write_tokens", 0),
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
