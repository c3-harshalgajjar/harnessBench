"""Pydantic models describing the suite, harnesses, tasks, and run results.

These are the single schema the whole orchestrator agrees on. Everything else
(runner, scoring, telemetry, report) reads and writes these shapes.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class Category(str, Enum):
    react = "react"
    mcp = "mcp"
    browser = "browser"
    context_fill = "context-fill"


class Difficulty(str, Enum):
    low = "low"
    mid = "mid"
    high = "high"


class McpServerSpec(BaseModel):
    """A deterministic MCP server a task wires into the harness under test."""

    name: str
    command: str
    args: list[str] = Field(default_factory=list)


class Task(BaseModel):
    """One benchmark task: a starting workspace, a prompt, and hidden tests."""

    id: str
    category: Category
    difficulty: Difficulty
    prompt: str
    timeout_seconds: int = 1800
    mcp: list[McpServerSpec] = Field(default_factory=list)
    # Directory that holds this task on disk (workspace/, tests/, mcp/, reference/).
    root: Path

    @classmethod
    def load(cls, task_dir: Path) -> "Task":
        meta = yaml.safe_load((task_dir / "task.yaml").read_text())
        meta["root"] = task_dir
        return cls(**meta)

    @property
    def workspace_dir(self) -> Path:
        return self.root / "workspace"

    @property
    def tests_dir(self) -> Path:
        return self.root / "tests"

    @property
    def reference_dir(self) -> Path:
        # Optional reference solution used by `verify-task`.
        return self.root / "reference"


class Harness(BaseModel):
    """A harness under test. `eligible` gates the SCORED tier.

    A harness is scored only if it will route traffic through our proxy base URL
    (so we can pin the model + thinking budget server-side). Harnesses that
    hard-route through their own gateway are eligible=False and land in the
    unmatched appendix, never on a scored leaderboard row.
    """

    name: str
    adapter: str  # module name under harnessbench.adapters
    eligible: bool = True
    # If this harness must run on the host instead of in-container (Bob), flag it.
    run_on_host: bool = False
    # Opt into host execution ONLY in the no-key (direct) path — e.g. Claude Code with
    # subscription OAuth, whose credential lives in the host Keychain and can't be
    # mounted into a Linux container. Distinct from Bob's always-host `run_on_host`.
    run_on_host_when_no_key: bool = False
    inner_harness_configurable: bool = False  # bob only


class Suite(BaseModel):
    """The full run configuration: which model/thinking to pin, which harnesses,
    how many trials, which tasks."""

    # The single logical model name every harness is told to use. The proxy
    # overwrites it to `pinned_model` + `thinking_budget_tokens` regardless.
    bench_model_name: str = "bench-model"
    pinned_model: str = "anthropic/claude-opus-4-8"
    thinking_budget_tokens: int = 8192
    # Model alias handed to a harness in DIRECT (no-key) mode, where no proxy exists
    # to rewrite `bench_model_name`. Must be an alias the harness resolves natively
    # (e.g. Claude Code's `opus` -> latest Opus).
    direct_model_alias: str = "opus"
    trials: int = 3
    harnesses: list[Harness]
    task_ids: list[str] = Field(default_factory=list)  # empty = all discovered


class RunResult(BaseModel):
    """One row in runs.jsonl: a single (task x harness x trial) execution."""

    run_id: str
    task_id: str
    category: Category
    difficulty: Difficulty
    harness: str
    inner_harness: str | None = None  # bob only
    trial: int

    # How this run was executed:
    #   "proxied" — traffic went through the LiteLLM proxy; model+thinking pinned
    #               server-side; tokens are proxy-authoritative.
    #   "direct"  — no API key; harness ran on the host with its own (subscription)
    #               auth; nothing pinned; tokens are the harness's self-report.
    run_mode: Literal["proxied", "direct"] = "proxied"
    # True only when token counts came from the proxy log. The report never ranks a
    # verified count against a self-reported one.
    tokens_verified: bool = False

    # Model parity assertion — every proxied request must resolve to these.
    resolved_model: str | None = None
    resolved_thinking_budget: int | None = None
    model_parity_ok: bool = True  # False => run invalid, excluded from scoring

    # Outcome
    passed: bool = False
    timed_out: bool = False
    error: str | None = None

    # Speed
    wall_seconds: float = 0.0

    # Tokens (proxy = source of truth)
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    num_requests: int = 0
    num_tool_calls: int = 0

    # Cross-check from the harness's own reporting (divergence audit only).
    native_total_tokens: int | None = None

    # Compaction-only metrics (context-fill category).
    turns_to_first_compaction: int | None = None
    token_growth_slope: float | None = None
    post_compaction_passed: bool | None = None
