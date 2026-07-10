# harnessbench

**Benchmark coding-agent harnesses — not the model.**

`harnessbench` measures how much a *coding-agent harness* (Claude Code, opencode,
Pi, Codex, Bob, Cursor CLI, …) costs you in **tokens**, **wall-clock time**, and
**context-compaction quality** — while holding the underlying model perfectly
constant across every harness.

The insight: two harnesses running the *same model* on the *same task* can differ
by an order of magnitude in tokens burned, depending on how they build context,
call tools, and compact history. That difference is the harness. This suite
isolates it.

---

## The load-bearing idea: the model is a controlled variable

Every scored harness runs **byte-for-byte the same model at the same thinking
budget**, pinned *server-side* so no harness default, gateway preset, or
reasoning slider can perturb the comparison.

All harness LLM traffic is forced through a local **LiteLLM proxy**. The proxy
exposes one logical model name — `bench-model` — that every harness is told to
use. Server-side, that name is rewritten to a fixed model
(`anthropic/claude-opus-4-8`) at a fixed thinking budget. A harness asking for
"opus", "sonnet", or "auto" still gets exactly `bench-model`. The proxy is also
the single source of truth for token counts: it logs one row per request, and
`telemetry.py` asserts every request resolved to the pinned model + budget. Any
run with a mismatched request is marked invalid and excluded from scoring.

**A harness is only eligible for the scored leaderboard if it will send its
traffic to a base URL we control.** Harnesses that hard-route through their own
hosted gateway (e.g. Cursor CLI's hosted Opus, where thinking is baked into the
model name and isn't independently controllable) **cannot be model-matched** and
are excluded from the scored tier. They may appear in a clearly-labeled
*unmatched appendix*, but never share a leaderboard row with matched harnesses.

---

## What it measures

| Metric | Source | Why |
|---|---|---|
| **Total tokens** (input / output / cache-read / cache-write split) | LiteLLM proxy log | The authoritative, cross-harness-comparable cost |
| **Wall-clock seconds** | `/usr/bin/time` around dispatch | First-class metric, co-equal with pass rate |
| **Pass / fail** | Deterministic hidden tests | Not LLM-as-judge — objective scoring |
| **Tokens-per-pass** | derived | Efficiency: cost normalized by success |
| **Compaction quality** | context-fill tasks | Does it stay accurate as the window fills? |
| **Native tokens** (cross-check) | each harness's own reporting | Divergence audit vs. the proxy truth |

---

## The four task axes

Each task is a directory with a starting `workspace/`, a natural-language
`prompt`, and **hidden** `tests/` (never shown to the harness). Categories:

1. **`react/`** — real-ish React apps (Vite). Fix a component, add a feature,
   refactor a hook. Scored by Vitest + Testing Library.
   *Seed:* `react-cart-total-bug` — a shopping cart whose subtotal and
   free-shipping banner don't recompute.
2. **`mcp/`** — solvable only by calling a provided **MCP server**. We ship a
   small deterministic stdio MCP server per task, wired into each harness's MCP
   config. Scored by asserting the side effect the tool produced.
   *Seed:* `mcp-secret-retrieval` — the answer token is *only* obtainable by
   calling the `vault` MCP tool, so a pass proves the harness exercised MCP.
3. **`browser/`** — requires **Playwright** automation against a served local
   site. Scored on the produced artifact + a check that the browser was actually
   driven.
   *Seed:* `browser-scrape-price` — scrape on-sale products from a static site,
   emit a sorted JSON report.
4. **`context-fill/`** — deliberately overflow the context window, then require
   correct action on information from *early* in the run — forcing retention
   across a compaction boundary. This is the compaction probe.
   *Seed:* `context-fill-ledger-audit` — 400 synthetic module files with LEDGER
   entries scattered throughout (including the earliest files a naive harness
   evicts first); compute the net balance per ID.

Every task carries `difficulty: low | mid | high` so harness differences are
visible without the bench being all-or-nothing.

### Tasks are deterministic and drift-proof

Tasks with large or generated fixtures ship a `gen.py` that produces **both** the
workspace and the ground-truth answer from a single fixed seed. Fixture and
grader can never disagree, because they come from the same computation. The
output is committed, so the runner mounts `workspace/` directly with no build
step.

---

## How a run works

For each `(task × harness × trial)`:

1. `docker run` the base image with the task `workspace/` mounted read-write.
   `tests/` are **not** mounted yet (the harness never sees them).
2. `entrypoint.sh` sanitizes the environment: deletes steering files
   (`CLAUDE.md`, `AGENTS.md`, `.cursor/`, `.claude/`, …), cleans `HOME`, and
   materializes the task's MCP config at `/harnessbench/mcp.json`.
3. The adapter dispatches the harness's **headless** command, pointing its
   provider base URL at the proxy and telling it to use `bench-model`.
4. On exit (or per-task timeout), hidden tests are copied in and run inside the
   container → pass/fail. Wall-time and the proxy token sum are collected.
5. One row is written to `runs.jsonl`; the container is torn down.

Bob is the one documented exception — it shells out to an inner runtime and runs
**on the host** against a mounted workspace, with its inner `claude` runtime
pointed at the same proxy. It's scored only within its inner-runtime cohort.

---

## Repository layout

```
benchmarks/harnessbench/
  pyproject.toml            # orchestrator deps
  suite.yaml                # which model/thinking to pin, which harnesses, trials
  harnessbench/             # the Python orchestrator
    cli.py                  # `harnessbench list-tasks | run | report`
    config.py               # pydantic models: Suite, Harness, Task, RunResult
    runner.py               # per-run orchestration
    docker_run.py           # `docker run` wrapper, volume mounts, MCP wiring
    scoring.py              # runs hidden tests inside the container
    telemetry.py            # aggregates proxy usage + asserts model parity
    report.py               # runs.jsonl -> markdown leaderboard
    proxy_manager.py        # start/health/stop the LiteLLM proxy
    tasks.py                # discover tasks under tasks/
    adapters/               # one adapter per harness
      base.py               # Adapter ABC
      claude.py  opencode.py  pi.py  codex.py  cursor.py  bob.py
  proxy/
    litellm_config.yaml     # maps bench-model -> pinned model + thinking budget
    usage_logger.py         # LiteLLM callback -> one JSONL row per request
  docker/
    Dockerfile.base         # node + python + Playwright + all harness CLIs
    entrypoint.sh           # sanitize steering, materialize MCP, dispatch
  tasks/
    react-cart-total-bug/       (react   / low)
    mcp-secret-retrieval/       (mcp     / low)
    browser-scrape-price/       (browser / mid)
    context-fill-ledger-audit/  (context-fill / high)
  results/
    runs.jsonl              # one row per (task x harness x trial)
    leaderboard.md
```

---

## Quickstart

```bash
cd benchmarks/harnessbench

# 1. Install the orchestrator (+ the proxy extra).
pip install -e ".[proxy]"

# 2. Build the base image (node + python + Playwright + harness CLIs).
docker build -f docker/Dockerfile.base -t harnessbench-base:latest docker/

# 3. Put your real provider key where the PROXY (not the harness) can see it.
export ANTHROPIC_API_KEY=sk-ant-...   # stays server-side in the proxy only

# 4. List the seed tasks.
harnessbench list-tasks

# 5. Run the suite (starts the proxy, dispatches every eligible harness,
#    scores with hidden tests, writes the leaderboard).
harnessbench run --suite suite.yaml --out results/

# 6. Rebuild the leaderboard from an existing run.
harnessbench report --out results/
```

The leaderboard splits harnesses into **Scored** (`model_parity_ok = true`) and
an **Unmatched appendix** (parity-failed or ineligible), ranked primarily by
tokens-per-pass among harnesses with comparable pass rates.

---

## Status

v1 is a working skeleton plus four seed tasks (one per category). It is honestly
**underpowered** for firm success-rate claims — research puts that at 100–300
tasks — but the suite is built to scale to that. The report prints its own
statistical power so you never over-read a small run.

Out of scope for v1: multi-model sweeps (one model is pinned by design), a hosted
web leaderboard (local markdown/CSV only), and dollar-cost conversion (tokens are
recorded; a price table is a trivial later add).

See [`docs/specs/harness-benchmark.md`](docs/specs/harness-benchmark.md) for the
full design rationale, the research pass on why existing benchmarks don't answer
this, and the verification plan.
