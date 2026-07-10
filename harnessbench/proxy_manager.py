"""Proxy lifecycle: start/stop the LiteLLM proxy that pins model+thinking and logs
authoritative usage.

The proxy binds on the host; containers reach it via host.docker.internal (mapped in
the runner's docker run args). The real ANTHROPIC_API_KEY lives only in the proxy's
environment, never in a harness container.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import httpx

PROXY_DIR = Path(__file__).resolve().parent.parent / "proxy"


class Proxy:
    def __init__(
        self,
        port: int,
        usage_log: Path,
        proxy_key: str,
        config: Path | None = None,
    ):
        self.port = port
        self.usage_log = usage_log
        self.proxy_key = proxy_key
        self.config = config or (PROXY_DIR / "litellm_config.yaml")
        self._proc: subprocess.Popen | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        if "ANTHROPIC_API_KEY" not in os.environ:
            raise RuntimeError(
                "ANTHROPIC_API_KEY must be set in the orchestrator env; it is the "
                "only place the real provider key lives."
            )
        env = dict(os.environ)
        env["HARNESSBENCH_USAGE_LOG"] = str(self.usage_log)
        env["HARNESSBENCH_PROXY_KEY"] = self.proxy_key
        # Ensure litellm can import the callback by dotted path.
        env["PYTHONPATH"] = str(PROXY_DIR.parent) + os.pathsep + env.get("PYTHONPATH", "")
        self.usage_log.parent.mkdir(parents=True, exist_ok=True)
        self._proc = subprocess.Popen(
            ["litellm", "--config", str(self.config), "--port", str(self.port)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        self._wait_healthy()

    def _wait_healthy(self, timeout: float = 60.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._proc and self._proc.poll() is not None:
                raise RuntimeError("litellm proxy exited during startup")
            try:
                r = httpx.get(f"{self.base_url}/health/liveliness", timeout=2.0)
                if r.status_code < 500:
                    return
            except Exception:
                pass
            time.sleep(1.0)
        raise RuntimeError("litellm proxy did not become healthy in time")

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    def __enter__(self) -> "Proxy":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
