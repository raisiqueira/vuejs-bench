import argparse
import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vuebench.agents import AGENT_NAMES, DEFAULT_TIMEOUT_SECONDS, create_agent_runner
from vuebench.benchmark import Benchmark, BenchmarkExecutionError, default_tasks_root
from vuebench.models import BenchmarkResult
from vuebench.tasks.discovery import discover_tasks
from vuebench.verification.runner import (
    DEFAULT_COMMAND_TIMEOUT_SECONDS,
    DEFAULT_SANDBOX_NAME,
    HiddenVerifier,
    VerifierUnavailable,
)


def _add_run_arguments(parser: argparse.ArgumentParser, *, suppress_defaults: bool = False) -> None:
    default = argparse.SUPPRESS if suppress_defaults else None
    parser.add_argument("--task", default=default, help="Run only the task with this id")
    parser.add_argument(
        "--agent",
        choices=AGENT_NAMES,
        default=argparse.SUPPRESS if suppress_defaults else "codex",
        help="Host-native coding-agent CLI (default: codex)",
    )
    parser.add_argument("--model", default=default, help="Optional model override for the agent")
    parser.add_argument(
        "--timeout",
        type=float,
        default=argparse.SUPPRESS if suppress_defaults else DEFAULT_TIMEOUT_SECONDS,
        help="Maximum seconds per agent trial (default: 900)",
    )
    parser.add_argument(
        "--tasks-root",
        type=Path,
        default=argparse.SUPPRESS if suppress_defaults else default_tasks_root(),
    )
    parser.add_argument(
        "--verifier-sandbox",
        default=argparse.SUPPRESS if suppress_defaults else DEFAULT_SANDBOX_NAME,
        help=f"Persistent SBX verifier name (default: {DEFAULT_SANDBOX_NAME})",
    )
    parser.add_argument(
        "--sbx-timeout",
        type=float,
        default=(argparse.SUPPRESS if suppress_defaults else DEFAULT_COMMAND_TIMEOUT_SECONDS),
        help="Maximum seconds for each SBX command (default: 300)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=default,
        help="JSON result path (default: generated under results/)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        default=argparse.SUPPRESS if suppress_defaults else False,
        help="Do not write a JSON result file",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vuebench", description="Run the VueBench agent benchmark"
    )
    _add_run_arguments(parser)
    subparsers = parser.add_subparsers(dest="command")
    list_parser = subparsers.add_parser("list", help="List configured benchmark tasks")
    list_parser.add_argument("--tasks-root", type=Path, default=default_tasks_root())
    run_parser = subparsers.add_parser("run", help="Run benchmark tasks")
    _add_run_arguments(run_parser, suppress_defaults=True)
    verifier_parser = subparsers.add_parser(
        "verifier", help="Manage the persistent Docker Sandbox verifier"
    )
    verifier_parser.add_argument("action", choices=("init", "status", "remove"))
    verifier_parser.add_argument("--name", default=DEFAULT_SANDBOX_NAME)
    verifier_parser.add_argument("--timeout", type=float, default=DEFAULT_COMMAND_TIMEOUT_SECONDS)
    parser.set_defaults(command="run")
    return parser


def _generated_output_path(*, task: str | None, agent: str, started: datetime) -> Path:
    timestamp = started.strftime("%Y%m%dT%H%M%SZ")
    scope = _filename_component(task or "all")
    return Path("results") / f"{timestamp}-{scope}-{_filename_component(agent)}.json"


def _filename_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.") or "run"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _result_payload(
    *,
    started: datetime,
    agent: str,
    model: str | None,
    results: list[BenchmarkResult] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "failed" if error else "completed",
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "agent": agent,
        "model": model,
        "error": error,
        "results": [result.model_dump(mode="json") for result in results or []],
    }


def _manage_verifier(args: argparse.Namespace) -> None:
    verifier = HiddenVerifier(
        sandbox_name=args.name,
        command_timeout_seconds=args.timeout,
    )
    try:
        if args.action == "init":
            print(f"Preparing verifier sandbox {args.name}...", flush=True)
            verifier.preflight()
            print(f"Verifier sandbox {args.name} is ready.")
        elif args.action == "status":
            status = verifier.status()
            if status is None:
                print(f"Verifier sandbox {args.name} does not exist.")
            else:
                print(json.dumps(status, indent=2, sort_keys=True))
        else:
            removed = verifier.remove()
            print(
                f"Verifier sandbox {args.name} removed."
                if removed
                else f"Verifier sandbox {args.name} does not exist."
            )
    except VerifierUnavailable as error:
        raise SystemExit(f"Verifier command failed: {error}") from error


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "verifier":
        _manage_verifier(args)
        return

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

    started = datetime.now(UTC)
    output_path = None
    if not args.no_save:
        output_path = args.output or _generated_output_path(
            task=args.task,
            agent=args.agent,
            started=started,
        )

    verifier = HiddenVerifier(
        sandbox_name=args.verifier_sandbox,
        command_timeout_seconds=args.sbx_timeout,
    )
    benchmark = Benchmark(
        agent=create_agent_runner(args.agent, timeout_seconds=args.timeout),
        agent_name=args.agent,
        verifier=verifier,
        progress=lambda message: print(message, flush=True),
    )
    try:
        results = asyncio.run(benchmark.run(selected, model=args.model))
    except BenchmarkExecutionError as exc:
        message = f"Benchmark failed: {exc}"
        if output_path is not None:
            _write_json(
                output_path,
                _result_payload(
                    started=started,
                    agent=args.agent,
                    model=args.model,
                    error=message,
                ),
            )
            message += f"\nPartial result: {output_path.resolve()}"
        raise SystemExit(message) from exc

    if output_path is not None:
        _write_json(
            output_path,
            _result_payload(
                started=started,
                agent=args.agent,
                model=args.model,
                results=results,
            ),
        )

    print("VueBench\n")
    for result in results:
        tests = "PASS" if result.verification.tests_passed else "FAIL"
        types = "PASS" if result.verification.typecheck_passed else "FAIL"
        outcome = "PASS" if result.verification.passed else "FAIL"
        print(result.task_id)
        print(f"  agent: {result.agent_name} (exit {result.agent.exit_code})")
        print(f"  tests: {tests}")
        print(f"  typecheck: {types}")
        print(f"  result: {outcome}")
        print(f"  duration: {result.agent.duration_seconds:.1f}s\n")
    passed = sum(result.verification.passed for result in results)
    percentage = (passed / len(selected) * 100) if selected else 0.0
    print("Summary")
    print(f"{passed} / {len(selected)} passed")
    print(f"{percentage:.1f}%")
    if output_path is not None:
        print(f"Result: {output_path.resolve()}")
