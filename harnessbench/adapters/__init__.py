"""Adapter registry: map the `adapter` name in suite config to a class."""

from __future__ import annotations

from harnessbench.adapters.base import Adapter
from harnessbench.adapters.bob import BobAdapter
from harnessbench.adapters.claude import ClaudeAdapter
from harnessbench.adapters.codex import CodexAdapter
from harnessbench.adapters.cursor import CursorAdapter
from harnessbench.adapters.opencode import OpencodeAdapter
from harnessbench.adapters.pi import PiAdapter
from harnessbench.config import Suite

REGISTRY: dict[str, type[Adapter]] = {
    "claude": ClaudeAdapter,
    "opencode": OpencodeAdapter,
    "pi": PiAdapter,
    "codex": CodexAdapter,
    "cursor": CursorAdapter,
    "bob": BobAdapter,
}


def get_adapter(
    name: str, suite: Suite, proxy_base_url: str, proxy_key: str
) -> Adapter:
    if name not in REGISTRY:
        raise KeyError(f"unknown adapter {name!r}; known: {sorted(REGISTRY)}")
    return REGISTRY[name](suite, proxy_base_url, proxy_key)
