from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext

from vuebench.agents.base import AgentRunner
from vuebench.models import BenchmarkResult, BenchmarkTask
from vuebench.tasks.workspace import WorkspaceManager
from vuebench.verification.runner import HiddenVerifier


class BenchmarkExecutionError(RuntimeError):
    """Raised when one or more benchmark cases could not be executed."""

    def __init__(self, failures: list[Any]) -> None:
        self.failures = failures
        details = "; ".join(f"{failure.name}: {failure.error_message}" for failure in failures)
        super().__init__(f"{len(failures)} benchmark case(s) failed to execute: {details}")


class VerificationInfrastructureError(RuntimeError):
    """Raised when a case could not be graded by its verification backend."""


@dataclass
class BenchmarkCaseInput:
    task: BenchmarkTask
    model: str | None = None


class DeterministicEvaluator(Evaluator):
    """Pydantic Evals evaluator whose verdict is entirely deterministic."""

    def evaluate(self, ctx: EvaluatorContext) -> dict[str, EvaluationReason]:
        result = ctx.output
        return {
            "passed": EvaluationReason(
                value=result.verification.passed,
                reason="Vitest and vue-tsc both passed"
                if result.verification.passed
                else "At least one deterministic verification check failed",
            ),
            "tests_passed": EvaluationReason(value=result.verification.tests_passed),
            "typecheck_passed": EvaluationReason(value=result.verification.typecheck_passed),
        }


class Benchmark:
    def __init__(
        self,
        *,
        agent: AgentRunner,
        workspace_manager: WorkspaceManager | None = None,
        verifier: HiddenVerifier | None = None,
        source_repo_root: Path | None = None,
    ) -> None:
        self.agent = agent
        self.workspace_manager = workspace_manager or WorkspaceManager()
        self.verifier = verifier or HiddenVerifier()
        self.source_repo_root = source_repo_root.resolve() if source_repo_root else None
        self.last_report: Any = None

    async def run_task(self, task: BenchmarkTask, *, model: str | None = None) -> BenchmarkResult:
        with self.workspace_manager.create(task) as task_workspace:
            agent_result = await self.agent.run(
                cwd=task_workspace.path,
                source_repo_root=self.source_repo_root or _find_repository_root(task.path),
                prompt=task.instruction,
                model=model,
            )
            verification = self.verifier.run(
                task_verifier=task.verifier_path,
                workspace=task_workspace.path,
                starter=task.starter_path,
                node=task.runtime.node,
                package_manager=task.runtime.package_manager,
            )
            if verification.infrastructure_error:
                raise VerificationInfrastructureError(
                    f"{task.id}: {verification.infrastructure_error}"
                )
        return BenchmarkResult(
            task_id=task.id,
            task_title=task.title,
            category=task.category,
            difficulty=task.difficulty,
            agent=agent_result,
            verification=verification,
        )

    async def run(
        self, tasks: list[BenchmarkTask], *, model: str | None = None
    ) -> list[BenchmarkResult]:
        """Evaluate all tasks as Pydantic Evals cases and return structured outputs."""
        cases = [
            Case(
                name=task.id,
                inputs=BenchmarkCaseInput(task=task, model=model),
                metadata={"category": task.category, "difficulty": task.difficulty},
            )
            for task in tasks
        ]
        dataset = Dataset(name="vuebench", cases=cases, evaluators=[DeterministicEvaluator()])

        async def execute(case_input: BenchmarkCaseInput) -> BenchmarkResult:
            return await self.run_task(case_input.task, model=case_input.model)

        # Pydantic Evals is deliberately the experiment/case layer. Correctness
        # remains the VerificationResult produced by Vitest and vue-tsc.
        report = await dataset.evaluate(execute, max_concurrency=1, progress=False)
        self.last_report = report
        if report.failures:
            raise BenchmarkExecutionError(report.failures)
        return [evaluation.output for evaluation in report.cases]


def default_tasks_root() -> Path:
    return Path(__file__).resolve().parents[2] / "tasks"


def _find_repository_root(path: Path) -> Path:
    """Find the checkout containing a task, failing before an unsafe run."""
    candidate = path.resolve()
    for parent in (candidate, *candidate.parents):
        if (parent / ".git").exists():
            return parent
    raise RuntimeError(
        f"unable to locate the benchmark Git repository for task {path}; "
        "refusing to run Codex without a source-repository read guard"
    )
