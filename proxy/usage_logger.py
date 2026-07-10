"""LiteLLM custom callback: one authoritative usage JSONL row per request.

This is the single source of truth for token counts across all harnesses. Because
every harness routes through the proxy, they all produce identically-shaped rows here
regardless of how (or whether) they self-report usage.

Each row also records the *resolved* model and thinking budget so telemetry.py can
assert model parity: if any request in a run resolved to something other than the
pinned model+budget, that run is invalid and excluded from scoring.

The active run_id is passed by the harness as the `x-harnessbench-run-id` header (the
adapter sets it), or falls back to the `HARNESSBENCH_RUN_ID` env var the container is
launched with.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from litellm.integrations.custom_logger import CustomLogger
except Exception:  # pragma: no cover - litellm only present in the proxy env
    class CustomLogger:  # type: ignore
        pass


_USAGE_LOG = Path(os.environ.get("HARNESSBENCH_USAGE_LOG", "/tmp/harnessbench_usage.jsonl"))
_LOCK = threading.Lock()


def _extract(obj: Any, *names: str, default: int = 0) -> int:
    for n in names:
        if isinstance(obj, dict) and obj.get(n) is not None:
            return int(obj[n])
        v = getattr(obj, n, None)
        if v is not None:
            return int(v)
    return default


class HarnessBenchUsageLogger(CustomLogger):
    def log_success_event(self, kwargs, response_obj, start_time, end_time):  # noqa: D401
        self._write(kwargs, response_obj, start_time, end_time, ok=True)

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        self._write(kwargs, response_obj, start_time, end_time, ok=True)

    def log_failure_event(self, kwargs, response_obj, start_time, end_time):
        self._write(kwargs, response_obj, start_time, end_time, ok=False)

    def _write(self, kwargs, response_obj, start_time, end_time, ok: bool) -> None:
        litellm_params = kwargs.get("litellm_params", {}) or {}
        metadata = litellm_params.get("metadata", {}) or {}
        headers = metadata.get("headers", {}) or {}

        run_id = (
            headers.get("x-harnessbench-run-id")
            or metadata.get("x-harnessbench-run-id")
            or os.environ.get("HARNESSBENCH_RUN_ID")
            or "unknown"
        )

        usage = getattr(response_obj, "usage", None) or {}
        # Anthropic-shaped cache token fields live under different keys depending on
        # litellm version; probe the common ones.
        prompt = _extract(usage, "prompt_tokens", "input_tokens")
        completion = _extract(usage, "completion_tokens", "output_tokens")
        cache_read = _extract(usage, "cache_read_input_tokens", "cache_read_tokens")
        cache_write = _extract(usage, "cache_creation_input_tokens", "cache_write_tokens")

        # What the request ACTUALLY resolved to, for the parity assertion.
        resolved_model = kwargs.get("model") or litellm_params.get("model")
        thinking = (litellm_params.get("thinking") or {})
        resolved_budget = None
        if isinstance(thinking, dict):
            resolved_budget = thinking.get("budget_tokens")

        try:
            latency = (end_time - start_time).total_seconds()
        except Exception:
            latency = None

        row = {
            "run_id": run_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "ok": ok,
            "resolved_model": resolved_model,
            "resolved_thinking_budget": resolved_budget,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
            "latency_seconds": latency,
        }
        with _LOCK:
            _USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with _USAGE_LOG.open("a") as fh:
                fh.write(json.dumps(row) + "\n")


usage_callback_instance = HarnessBenchUsageLogger()
