"""harnessbench CLI: run the suite, build the report, list tasks/harnesses.

Commands:
    harnessbench list-tasks
    harnessbench run --suite suite.yaml --out results/
    harnessbench report --out results/            # rebuild leaderboard from runs.jsonl
"""

from __future__ import annotations

from pathlib import Path

import click
import yaml
from rich.console import Console

from harnessbench.config import Suite
from harnessbench.report import build_report
from harnessbench.runner import Runner
from harnessbench.tasks import discover_tasks

console = Console()


@click.group()
def main() -> None:
    """Benchmark coding-agent harnesses with a server-pinned model+thinking budget."""


@main.command("list-tasks")
def list_tasks() -> None:
    tasks = discover_tasks()
    if not tasks:
        console.print("[yellow]no tasks found under tasks/[/]")
        return
    for t in tasks.values():
        console.print(f"[bold]{t.id}[/] [{t.category.value}/{t.difficulty.value}]")


@main.command("run")
@click.option("--suite", "suite_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--out", "out_dir", type=click.Path(path_type=Path), default=Path("results"))
@click.option("--image", default="harnessbench-base:latest")
@click.option("--proxy-port", default=4000, type=int)
def run_cmd(suite_path: Path, out_dir: Path, image: str, proxy_port: int) -> None:
    suite = Suite(**yaml.safe_load(suite_path.read_text()))
    tasks = discover_tasks()
    runner = Runner(suite, tasks, out_dir, image=image, proxy_port=proxy_port)
    console.print(
        f"[bold]Running[/] {len(runner._selected_tasks())} tasks x "
        f"{len(suite.harnesses)} harnesses x {suite.trials} trials"
    )
    results = runner.run()
    scored = sum(1 for r in results if r.trial >= 0 and r.model_parity_ok)
    console.print(f"[green]done[/] — {len(results)} rows ({scored} scored) -> {runner.runs_log}")
    report = build_report(runner.runs_log)
    (out_dir / "leaderboard.md").write_text(report)
    console.print(f"[green]leaderboard[/] -> {out_dir / 'leaderboard.md'}")


@main.command("report")
@click.option("--out", "out_dir", type=click.Path(exists=True, path_type=Path), default=Path("results"))
def report_cmd(out_dir: Path) -> None:
    runs_log = out_dir / "runs.jsonl"
    if not runs_log.exists():
        console.print(f"[red]no runs.jsonl in {out_dir}[/]")
        raise SystemExit(1)
    report = build_report(runs_log)
    (out_dir / "leaderboard.md").write_text(report)
    console.print(report)


if __name__ == "__main__":
    main()
