import argparse
import asyncio
from pathlib import Path

from vuebench.agents.codex import DEFAULT_TIMEOUT_SECONDS, CodexRunner
from vuebench.benchmark import Benchmark, BenchmarkExecutionError, default_tasks_root
from vuebench.tasks.discovery import discover_tasks


def _add_run_arguments(parser: argparse.ArgumentParser, *, suppress_defaults: bool = False) -> None:
    default = argparse.SUPPRESS if suppress_defaults else None
    parser.add_argument("--task", default=default, help="Run only the task with this id")
    parser.add_argument("--model", default=default, help="Optional Codex model override")
    parser.add_argument(
        "--timeout",
        type=float,
        default=argparse.SUPPRESS if suppress_defaults else DEFAULT_TIMEOUT_SECONDS,
        help="Maximum seconds per Codex trial (default: 900)",
    )
    parser.add_argument(
        "--tasks-root",
        type=Path,
        default=argparse.SUPPRESS if suppress_defaults else default_tasks_root(),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vuebench", description="Run the VueBench agent benchmark"
    )
    _add_run_arguments(parser)
    subparsers = parser.add_subparsers(dest="command")
    list_parser = subparsers.add_parser("list", help="List configured benchmark tasks")
    list_parser.add_argument("--tasks-root", type=Path, default=default_tasks_root())
    run_parser = subparsers.add_parser("run", help="Run benchmark tasks with Codex")
    _add_run_arguments(run_parser, suppress_defaults=True)
    parser.set_defaults(command="run")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    tasks = discover_tasks(args.tasks_root)
    if args.command == "list":
        print("VueBench tasks\n")
        for task in tasks:
            print(
                f"{task.id}\n  {task.title}\n  category: {task.category}\n"
                f"  difficulty: {task.difficulty}\n"
            )
        return

    selected = [task for task in tasks if args.task is None or task.id == args.task]
    if not selected:
        raise SystemExit(f"Unknown task: {args.task}")
    try:
        results = asyncio.run(
            Benchmark(agent=CodexRunner(timeout_seconds=args.timeout)).run(
                selected, model=args.model
            )
        )
    except BenchmarkExecutionError as exc:
        raise SystemExit(f"Benchmark failed: {exc}") from exc
    print("VueBench\n")
    for result in results:
        tests = "PASS" if result.verification.tests_passed else "FAIL"
        types = "PASS" if result.verification.typecheck_passed else "FAIL"
        outcome = "PASS" if result.verification.passed else "FAIL"
        print(result.task_id)
        print(f"  agent: codex (exit {result.agent.exit_code})")
        print(f"  tests: {tests}")
        print(f"  typecheck: {types}")
        print(f"  result: {outcome}")
        print(f"  duration: {result.agent.duration_seconds:.1f}s\n")
    passed = sum(result.verification.passed for result in results)
    percentage = (passed / len(selected) * 100) if selected else 0.0
    print("Summary")
    print(f"{passed} / {len(selected)} passed")
    print(f"{percentage:.1f}%")
