"""Bob adapter — runs on the HOST, not in-container.

Bob is a multi-agent orchestrator that shells out to an inner runtime (claude /
cursor / local). Two modes:

  - proxied (key present): Bob's inner runtime is pointed at the proxy via
    ANTHROPIC_BASE_URL and pinned to `bench-model`; the proxy measures tokens
    authoritatively. Rows are comparable only within the same inner runtime.
  - direct (no key): the inner runtime uses its own host subscription auth (no
    base-URL override). Bob emits no usage on stdout, so tokens are read after the
    run from Bob's own SQLite cost ledger (~/.config/bob/cost.db) — see
    `usage_since()`. Those rows are self-reported/unverified.

Because Bob mutates local state and expects its own repo layout, it always runs on
the host against a throwaway copy of the task workspace.
Dispatch: `bob --auto --yes -m <prompt>`.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from harnessbench.adapters.base import Adapter
from harnessbench.config import Task

_COST_DB = Path(os.path.expanduser("~/.config/bob/cost.db"))


class BobAdapter(Adapter):
    name = "bob"

    def env(self, run_id: str) -> dict[str, str]:
        e = super().env(run_id)
        e.update(
            {
                "ANTHROPIC_BASE_URL": self.proxy_base_url,
                "ANTHROPIC_AUTH_TOKEN": self.proxy_key,
                "BOB_RUNTIME": "claude",  # inner runtime; recorded as inner_harness
            }
        )
        return e

    def env_direct(self, run_id: str) -> dict[str, str]:
        # No proxy override — Bob's inner runtime uses its own host subscription auth.
        return {}

    def build_cmd(self, task: Task, run_id: str) -> list[str]:
        return ["bob", "--auto", "--yes", "-m", task.prompt]

    def build_cmd_direct(self, task: Task, run_id: str) -> list[str]:
        return self.build_cmd(task, run_id)

    @staticmethod
    def ledger_watermark() -> str:
        """Max ts currently in Bob's cost ledger, or '' if none/absent.

        Runner records this immediately BEFORE dispatching bob, then calls
        `usage_since(watermark)` after, to attribute exactly this run's tokens.
        Runs are serialized, so a ts-window is a reliable correlation key.
        """
        if not _COST_DB.exists():
            return ""
        try:
            con = sqlite3.connect(f"file:{_COST_DB}?mode=ro", uri=True)
            row = con.execute("SELECT MAX(ts) FROM usage").fetchone()
            con.close()
            return row[0] or "" if row else ""
        except sqlite3.Error:
            return ""

    @staticmethod
    def usage_since(watermark: str) -> dict[str, int | str] | None:
        """Sum cost-ledger usage rows newer than `watermark`. None if nothing/absent."""
        if not _COST_DB.exists():
            return None
        try:
            con = sqlite3.connect(f"file:{_COST_DB}?mode=ro", uri=True)
            row = con.execute(
                """
                SELECT
                    COALESCE(SUM(input_tokens), 0),
                    COALESCE(SUM(output_tokens), 0),
                    COALESCE(SUM(cache_read_tokens), 0),
                    COALESCE(SUM(cache_write_tokens), 0),
                    COUNT(*)
                FROM usage
                WHERE ts > ?
                """,
                (watermark,),
            ).fetchone()
            model_row = con.execute(
                "SELECT model FROM usage WHERE ts > ? ORDER BY ts DESC LIMIT 1",
                (watermark,),
            ).fetchone()
            con.close()
        except sqlite3.Error:
            return None
        if not row or row[4] == 0:
            return None
        inp, out, cr, cw, _n = row
        return {
            "input_tokens": int(inp),
            "output_tokens": int(out),
            "cache_read_tokens": int(cr),
            "cache_write_tokens": int(cw),
            "total_tokens": int(inp) + int(out),
            "resolved_model": (model_row[0] if model_row else "") or "",
        }

    def probe_eligible(self) -> bool:
        # Scored only within its inner-runtime cohort; the proxy still measures it.
        return True
