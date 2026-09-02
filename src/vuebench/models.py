from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class RuntimeConfig(BaseModel):
    node: int = 24
    package_manager: str = "pnpm"


class BenchmarkTask(BaseModel):
    """A task definition loaded from a task directory."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    title: str
    category: str
    difficulty: str
    path: Path
    instruction: str
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    checks: list[str] = Field(default_factory=lambda: ["vitest", "vue-tsc"])

    @property
    def starter_path(self) -> Path:
        return self.path / "starter"

    @property
    def verifier_path(self) -> Path:
        return self.path / "verifier"


class AgentResult(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    diff: str
    duration_seconds: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


class VerificationResult(BaseModel):
    tests_passed: bool
    typecheck_passed: bool
    tests_output: str
    typecheck_output: str
    passed: bool


class BenchmarkResult(BaseModel):
    task_id: str
    task_title: str
    category: str
    difficulty: str
    agent: AgentResult
    verification: VerificationResult
