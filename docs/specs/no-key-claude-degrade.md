# Spec: run Claude Code with subscription auth, no API key (graceful degradation)

## Problem

`harnessbench` was built around a hard invariant: **every harness routes through a
local LiteLLM proxy**, which pins the model + thinking budget server-side and is the
authoritative token log. That proxy needs a provider API key (`ANTHROPIC_API_KEY`)
in the orchestrator env to actually call Anthropic.

The user wants to benchmark **Claude Code** using its **subscription login** (the
Max/Pro OAuth token from `claude login`, stored in the macOS Keychain) — and has
**no API key**. Two load-bearing assumptions break:

1. **No proxy is possible.** With no API key, the LiteLLM proxy can't start (it
   `raise`s today). Claude Code's OAuth token is scoped to Anthropic's first-party
   Claude Code backend (`user:inference`); the proxy can't reuse it to make generic
   API calls, and Claude Code won't send its subscription traffic to an arbitrary
   base URL without being downgraded to API-key mode.
2. **In-container auth breaks.** The OAuth credential lives in the host Keychain.
   There is no Keychain in a Linux container, and the token is host-bound. Claude
   Code under subscription auth must run **on the host**, like the existing Bob
   exception — not in the container.

Today, `Runner.run()` unconditionally enters `with Proxy(...)`, and `Proxy.start()`
raises without `ANTHROPIC_API_KEY`. So a no-key invocation crashes before running a
single task. The user's directive: **"keep the existing code. We report whatever is
possible."** — i.e. degrade, don't crash, and don't rip out the parity design.

## Proposal

Make the whole pipeline **capability-gated on key presence**, with the parity design
fully intact when a key *is* present. One code path, two modes:

### Mode A — proxied (key present): unchanged
Exactly today's behavior. Proxy starts, pins model+thinking, logs authoritative
tokens, `model_parity_ok` can be `True`, harnesses run in-container.

### Mode B — direct (no key): new, degraded, clearly marked
- **Skip the proxy entirely.** `Runner.run()` decides `proxied = bool(os.environ.get("ANTHROPIC_API_KEY"))`. If false, don't construct `Proxy`; no `usage.jsonl`.
- **Claude Code runs on the host** against the copied workspace (not in-container),
  inheriting the host Keychain OAuth. No `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN`
  override — let it use subscription auth natively.
- **Tokens come from Claude Code's own `--output-format stream-json`** (self-reported,
  written to `native_total_tokens` + the split fields). `model_parity_ok = False`
  always in this mode, because nothing is server-pinned. These rows are **not**
  proxy-verified and the report must say so.
- **Pass/fail + wall-time still fully valid** — deterministic hidden tests need no key;
  wall-time is measured around dispatch regardless.
- **Hidden tests still run in-container** (hermetic, `--network none`) even when the
  harness ran on the host — the workspace is just a directory either way.

### Concrete changes (by file)

- **`config.py`**
  - `Harness`: add `run_on_host_when_no_key: bool = False` (Claude Code sets it) — lets
    a harness opt into host execution specifically for the no-key path, distinct from
    Bob's always-host `run_on_host`.
  - `RunResult`: add `tokens_verified: bool = False` (True only when proxy-sourced) and
    `run_mode: Literal["proxied","direct"]`. The report keys "scored vs unverified" off
    `tokens_verified`, not off `model_parity_ok` alone.
  - `Suite`: no change.
- **`proxy_manager.py`**
  - Keep the `ANTHROPIC_API_KEY` guard, but the *runner* is responsible for not calling
    `Proxy` when there's no key — the guard stays as a correctness assertion for Mode A.
- **`runner.py`**
  - Compute `self.proxied` from key presence in `__init__`.
  - `run()`: branch — if proxied, `with Proxy(...)` as today; else a no-proxy context
    that still iterates tasks × harnesses × trials.
  - `_one_run()`: parameterize on mode. In direct mode, dispatch on host, read
    `native_total_tokens` into the token fields, set `tokens_verified=False`,
    `run_mode="direct"`, `model_parity_ok=False`. In proxied mode, unchanged
    (`tokens_verified=True`).
  - Eligibility: in direct mode, a harness is "runnable" if it can auth natively on the
    host (Claude Code: yes). `probe_eligible()` (which asks "accepts our base URL")
    stops gating the *direct* path — it only gates the *scored* path. Non-Claude
    harnesses with no native host auth are recorded as skipped rows with a clear reason.
- **`docker_run.py`**
  - Add `run_on_host(adapter, task, run_id, work_copy)` that runs the adapter's argv
    directly on the host with `subprocess.run`, inheriting host env (so Keychain OAuth
    works), capturing stdout/stderr + wall + timeout. Mirrors `run_in_container`'s
    return contract.
- **`adapters/base.py`**
  - Add `def build_cmd_direct(self, task, run_id)` defaulting to `build_cmd`, and
    `def env_direct(self, run_id)` defaulting to `{}` (no proxy env). Lets an adapter
    express "how I run when NOT behind the proxy."
- **`adapters/claude.py`**
  - `env_direct`: return `{}` — no base-URL override, so subscription auth is used.
  - `build_cmd_direct`: same argv but `--model` uses a real alias (e.g. the suite's
    `pinned_model` short alias, default `opus`) instead of `bench-model`, since there's
    no proxy to rewrite `bench-model`. Add `--mcp-config` only when the task has MCP.
  - `parse_native_usage`: already sums stream-json usage — keep, and also capture the
    input/output/cache split so direct-mode rows have the same shape.
- **`report.py`**
  - Split the leaderboard into **"Proxy-verified (scored)"** (rows with
    `tokens_verified=True`) and **"Self-reported (unverified)"** (direct-mode rows).
    Never mix a verified and an unverified token count in the same ranking. Direct-mode
    section header states plainly: tokens are the harness's own numbers, model/thinking
    not pinned.
- **`suite.yaml`**
  - Mark `claude` with `run_on_host_when_no_key: true`. Everything else unchanged.
- **`README.md`**
  - New "Running without an API key" section documenting Mode B, what you get
    (pass/fail, wall-time, self-reported tokens) and what you lose (parity,
    proxy-verified tokens).

## Out of scope

- Making opencode / codex / pi work with *their* subscription logins in direct mode.
  The base plumbing (`build_cmd_direct` / host run) will exist, but only Claude Code is
  wired + verified in this change. Others fall through to "skipped: no native host auth
  in direct mode" until someone wires them.
- Any attempt to reverse-engineer the OAuth token into the proxy. Explicitly rejected:
  it's the wrong auth scope and against the spirit of subscription auth.
- Cursor CLI stays `eligible: false` regardless of mode.
- Changing the pinned model / thinking numbers.

## Verification plan

1. **Unit-ish**: `harnessbench list-tasks` still works (no key needed).
2. **Direct-mode smoke, no key**: `harnessbench run --suite suite.yaml` with
   `ANTHROPIC_API_KEY` unset and `task_ids: [react-cart-total-bug]`, harnesses scoped to
   `[claude]`. Expect: proxy NOT started; Claude Code runs on host; `runs.jsonl` has one
   row per trial with `run_mode="direct"`, `tokens_verified=false`,
   `model_parity_ok=false`, a real `wall_seconds`, `native_total_tokens>0`, and
   `passed` reflecting the hidden test.
3. **Report**: `leaderboard.md` shows Claude Code under "Self-reported (unverified)"
   with the disclaimer, and an empty (or absent) scored section.
4. **Regression (Mode A intact)**: with `ANTHROPIC_API_KEY` set (even a dummy that lets
   the proxy boot far enough to prove the branch), the runner still enters the proxy
   path and sets `tokens_verified=true`. (Full Mode A live run needs a real key — out of
   scope to execute here, but the branch is exercised.)
5. Artifact for approval: the actual `runs.jsonl` + rendered `leaderboard.md` from step
   2–3 on the one React task, pasted into the approval message.

## Open questions

None blocking. One noted assumption: in direct mode `--model opus` (Claude Code's alias
for the latest Opus) is used since `bench-model` only exists at the proxy. If the user
later wants a specific pinned Opus build in direct mode too, that's a one-line alias
change — called out in the README.
