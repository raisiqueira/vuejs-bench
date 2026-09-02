import asyncio
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from pydantic_evals.evaluators import EvaluatorContext

from vuebench import cli
from vuebench.agents.codex import (
    DEFAULT_TIMEOUT_SECONDS,
    CodexRunner,
    CodexSandboxUnavailable,
)
from vuebench.benchmark import Benchmark, BenchmarkExecutionError, DeterministicEvaluator
from vuebench.models import AgentResult, RuntimeConfig, VerificationResult
from vuebench.tasks.discovery import discover_tasks, load_task
from vuebench.tasks.workspace import WorkspaceManager
from vuebench.verification.runner import HiddenVerifier, parse_verification_result

REPO_ROOT = Path(__file__).parents[1]
TASKS_ROOT = REPO_ROOT / "tasks"


def test_discovery_loads_all_reactivity_tasks() -> None:
    tasks = discover_tasks(TASKS_ROOT)
    assert [task.id for task in tasks] == [
        "incorrect-watch-source",
        "reactive-destructure",
        "shallow-ref",
    ]
    assert all(task.instruction for task in tasks)
    assert all(task.starter_path.is_dir() for task in tasks)


def test_task_yaml_and_instruction_are_typed() -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    assert task.title == "Preserve reactivity after destructuring"
    assert task.runtime.node == 24
    assert task.runtime.package_manager == "pnpm"
    assert "CounterSummary.vue" in task.instruction


def test_runtime_rejects_node_versions_before_supported_floor() -> None:
    with pytest.raises(ValidationError):
        RuntimeConfig(node=23)


def test_hidden_verifier_rejects_nonpositive_timeout() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        HiddenVerifier(command_timeout_seconds=0)


class NoInstallWorkspaceManager(WorkspaceManager):
    def install_dependencies(self, workspace: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, "", "")


def test_workspace_is_pristine_and_does_not_mutate_starter() -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    starter_source = task.starter_path / "src" / "useCounter.ts"
    original = starter_source.read_text()
    workspace_path: Path
    with NoInstallWorkspaceManager().create(task) as workspace:
        workspace_path = workspace.path
        copied_source = workspace.path / "src" / "useCounter.ts"
        copied_source.write_text("changed")
        assert copied_source.read_text() == "changed"
        assert starter_source.read_text() == original
        assert (workspace.path / ".git").is_dir()
    assert not workspace_path.exists()
    assert starter_source.read_text() == original


class SuccessfulHiddenVerifier(HiddenVerifier):
    def __init__(self) -> None:
        super().__init__(sbx_executable="fake-sbx")
        self.commands: list[list[str]] = []

    def _run(
        self, command: list[str], *, cwd: Path, input_text: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        marker = re.search(r"printf 'VUEBENCH_STATUS:([^:]+):%s", command[-1])
        output = "ok"
        if marker:
            output += f"\nVUEBENCH_STATUS:{marker.group(1)}:0"
        return subprocess.CompletedProcess(command, 0, output, "")

    @staticmethod
    def _status_output(command: list[str], status: int) -> str:
        marker = re.search(r"printf 'VUEBENCH_STATUS:([^:]+):%s", command[-1])
        return f"ok\nVUEBENCH_STATUS:{marker.group(1)}:{status}" if marker else "ok"

def test_hidden_verifier_is_injected_only_for_checks_and_removed(tmp_path: Path) -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    verifier = SuccessfulHiddenVerifier()
    result = verifier.run(task_verifier=task.verifier_path, workspace=workspace)
    assert result.passed is True
    assert len(verifier.commands) == 7
    create, injection, volume, install, typecheck, tests, cleanup = verifier.commands
    assert create[:5] == ["fake-sbx", "create", "--clone", "--quiet", "--name"]
    sandbox_name = create[5]
    assert sandbox_name.startswith("vuebench-verify-")
    assert sandbox_name.replace("-", "").isalnum()
    assert create[6] == "shell"
    assert Path(create[7]).is_absolute()
    assert injection[:5] == ["fake-sbx", "exec", sandbox_name, "sh", "-lc"]
    assert injection[-1].startswith("mkdir -p ")
    assert volume[:6] == ["fake-sbx", "exec", sandbox_name, "docker", "volume", "create"]
    assert volume[-1].startswith("vuebench-tools-")
    assert install[:4] == ["fake-sbx", "exec", sandbox_name, "docker"]
    assert "npm install --prefix /vuebench-tools --ignore-scripts corepack@0.33.0" in install[-1]
    assert typecheck[:5] == ["fake-sbx", "exec", sandbox_name, "sh", "-lc"]
    assert "docker run --rm --network none" in typecheck[-1]
    assert ":ro" in typecheck[-1]
    assert "node:24-bookworm" in typecheck[-1]
    assert "vue-tsc" in typecheck[-1]
    assert "VUEBENCH_STATUS:" in typecheck[-1]
    assert tests[:5] == ["fake-sbx", "exec", sandbox_name, "sh", "-lc"]
    assert "vitest run" in tests[-1]
    assert "VUEBENCH_STATUS:" in tests[-1]
    assert cleanup == ["fake-sbx", "rm", "--force", sandbox_name]
    assert not (workspace / ".vuebench-hidden").exists()


def test_hidden_verifier_uses_unique_sandbox_names_and_runtime_node(tmp_path: Path) -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    verifier = SuccessfulHiddenVerifier()
    verifier.run(task_verifier=task.verifier_path, workspace=workspace, node=24)
    verifier.run(task_verifier=task.verifier_path, workspace=workspace, node=25)

    names = [command[5] for command in verifier.commands if command[1] == "create"]
    assert len(names) == 2
    assert len(set(names)) == 2
    assert all(name.startswith("vuebench-verify-") for name in names)
    assert any("node:24-bookworm" in command[-1] for command in verifier.commands)
    assert any("node:25-bookworm" in command[-1] for command in verifier.commands)


def test_hidden_verifier_fails_closed_and_cleans_up_when_sandbox_creation_fails(
    tmp_path: Path,
) -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class CreateFailureVerifier(SuccessfulHiddenVerifier):
        def _run(
            self, command: list[str], *, cwd: Path, input_text: str | None = None
        ) -> subprocess.CompletedProcess[str]:
            self.commands.append(command)
            if command[1] == "create":
                return subprocess.CompletedProcess(command, 1, "", "sbx unavailable")
            return subprocess.CompletedProcess(command, 0, "", "")

    verifier = CreateFailureVerifier()
    result = verifier.run(task_verifier=task.verifier_path, workspace=workspace)
    assert result.passed is False
    assert result.infrastructure_error is not None
    assert "creation" in result.infrastructure_error
    assert [command[1] for command in verifier.commands] == ["create", "rm"]


def test_hidden_verifier_fails_closed_and_cleans_up_on_sandbox_timeout(tmp_path: Path) -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class TimeoutVerifier(SuccessfulHiddenVerifier):
        def _run(
            self, command: list[str], *, cwd: Path, input_text: str | None = None
        ) -> subprocess.CompletedProcess[str]:
            self.commands.append(command)
            if command[1] == "exec":
                raise subprocess.TimeoutExpired(command, 1)
            return subprocess.CompletedProcess(command, 0, "", "")

    verifier = TimeoutVerifier()
    result = verifier.run(task_verifier=task.verifier_path, workspace=workspace)
    assert result.passed is False
    assert result.infrastructure_error is not None
    assert "timed out" in result.infrastructure_error
    assert [command[1] for command in verifier.commands] == ["create", "exec", "rm"]


def test_hidden_verifier_keeps_test_failures_distinct_from_sbx_failures(tmp_path: Path) -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class TestFailureVerifier(SuccessfulHiddenVerifier):
        def _run(
            self, command: list[str], *, cwd: Path, input_text: str | None = None
        ) -> subprocess.CompletedProcess[str]:
            self.commands.append(command)
            if "vitest run" in command[-1]:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    self._status_output(command, 1).replace("ok", "assertion failed"),
                    "",
                )
            return subprocess.CompletedProcess(command, 0, self._status_output(command, 0), "")

    result = TestFailureVerifier().run(task_verifier=task.verifier_path, workspace=workspace)
    assert result.passed is False
    assert result.tests_passed is False
    assert result.typecheck_passed is True
    assert result.infrastructure_error is None


def test_hidden_verifier_rejects_nonzero_outer_sbx_exec(tmp_path: Path) -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class OuterFailureVerifier(SuccessfulHiddenVerifier):
        def _run(
            self, command: list[str], *, cwd: Path, input_text: str | None = None
        ) -> subprocess.CompletedProcess[str]:
            self.commands.append(command)
            if "vitest run" in command[-1]:
                return subprocess.CompletedProcess(command, 1, "docker daemon failed", "")
            return subprocess.CompletedProcess(command, 0, self._status_output(command, 0), "")

    result = OuterFailureVerifier().run(task_verifier=task.verifier_path, workspace=workspace)
    assert result.passed is False
    assert result.infrastructure_error is not None
    assert "hidden tests execution" in result.infrastructure_error


@pytest.mark.parametrize("marker", ["", "VUEBENCH_STATUS:wrong-token:0\n", "garbage\n"])
def test_hidden_verifier_rejects_missing_or_invalid_status_marker(
    tmp_path: Path, marker: str
) -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class InvalidMarkerVerifier(SuccessfulHiddenVerifier):
        def _run(
            self, command: list[str], *, cwd: Path, input_text: str | None = None
        ) -> subprocess.CompletedProcess[str]:
            self.commands.append(command)
            if "vitest run" in command[-1] and marker:
                return subprocess.CompletedProcess(command, 0, f"ok\n{marker.strip()}", "")
            return subprocess.CompletedProcess(command, 0, "ok", "")

    result = InvalidMarkerVerifier().run(task_verifier=task.verifier_path, workspace=workspace)
    assert result.passed is False
    assert result.infrastructure_error is not None
    assert "status marker" in result.infrastructure_error


def test_hidden_verifier_rejects_unsupported_package_manager(tmp_path: Path) -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = SuccessfulHiddenVerifier().run(
        task_verifier=task.verifier_path,
        workspace=workspace,
        package_manager="npm",
    )
    assert result.passed is False
    assert result.infrastructure_error is not None
    assert "unsupported package manager" in result.infrastructure_error


def test_hidden_verifier_keeps_inner_typecheck_failure_scoreable(tmp_path: Path) -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class TypecheckFailureVerifier(SuccessfulHiddenVerifier):
        def _run(
            self, command: list[str], *, cwd: Path, input_text: str | None = None
        ) -> subprocess.CompletedProcess[str]:
            self.commands.append(command)
            if "vue-tsc" in command[-1]:
                return subprocess.CompletedProcess(command, 0, self._status_output(command, 2), "")
            return subprocess.CompletedProcess(command, 0, self._status_output(command, 0), "")

    result = TypecheckFailureVerifier().run(task_verifier=task.verifier_path, workspace=workspace)
    assert result.passed is False
    assert result.tests_passed is True
    assert result.typecheck_passed is False
    assert result.infrastructure_error is None


@pytest.mark.parametrize("docker_status", [125, 126, 127, 128])
def test_hidden_verifier_treats_container_statuses_as_infrastructure(
    tmp_path: Path, docker_status: int
) -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure/task.yaml")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class ContainerFailureVerifier(SuccessfulHiddenVerifier):
        def _run(
            self, command: list[str], *, cwd: Path, input_text: str | None = None
        ) -> subprocess.CompletedProcess[str]:
            self.commands.append(command)
            if "vue-tsc" in command[-1]:
                return subprocess.CompletedProcess(
                    command, 0, self._status_output(command, docker_status), ""
                )
            return subprocess.CompletedProcess(command, 0, self._status_output(command, 0), "")

    result = ContainerFailureVerifier().run(task_verifier=task.verifier_path, workspace=workspace)
    assert result.passed is False
    assert result.infrastructure_error is not None


def test_hidden_verifier_reports_cleanup_failure(tmp_path: Path) -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class CleanupFailureVerifier(SuccessfulHiddenVerifier):
        def _run(
            self, command: list[str], *, cwd: Path, input_text: str | None = None
        ) -> subprocess.CompletedProcess[str]:
            self.commands.append(command)
            if command[1] == "rm":
                return subprocess.CompletedProcess(command, 1, "", "permission denied")
            return subprocess.CompletedProcess(command, 0, "ok", "")

    result = CleanupFailureVerifier().run(task_verifier=task.verifier_path, workspace=workspace)
    assert result.passed is False
    assert result.infrastructure_error is not None
    assert "cleanup failed" in result.infrastructure_error


def test_hidden_verifier_ignores_tampered_harness_and_hidden_paths(tmp_path: Path) -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    workspace = tmp_path / "workspace"
    shutil.copytree(task.starter_path, workspace)

    # These are all candidate-controlled files. The verifier must not execute
    # the package script, accept a narrowed tsconfig, or collide with this path.
    (workspace / "package.json").write_text('{"scripts":{"vitest":"true"}}')
    (workspace / "vite.config.ts").write_text("export default {}")
    (workspace / "tsconfig.json").write_text('{"compilerOptions":{"strict":false}}')
    (workspace / ".vuebench-hidden").mkdir()
    (workspace / ".vuebench-hidden" / "fake.spec.ts").write_text("throw new Error('bypass')")
    (workspace / ".vuebench-corepack").mkdir()
    (workspace / ".vuebench-corepack" / "evil.cjs").write_text("process.exit(1)")
    (workspace / ".corepack.env").write_text("COREPACK_ENABLE_PROJECT_SPEC=1")
    (workspace / "node_modules/.bin/vitest").write_text("exit 0")
    (workspace / "src/CounterSummary.vue").write_text("candidate source")

    class InspectingVerifier(SuccessfulHiddenVerifier):
        def _run(
            self, command: list[str], *, cwd: Path, input_text: str | None = None
        ) -> subprocess.CompletedProcess[str]:
            self.commands.append(command)
            assert cwd != workspace
            assert (cwd / "package.json").read_text() == (
                task.starter_path / "package.json"
            ).read_text()
            assert (cwd / "vite.config.ts").read_text() == (
                task.starter_path / "vite.config.ts"
            ).read_text()
            assert (cwd / "tsconfig.json").read_text() == (
                task.starter_path / "tsconfig.json"
            ).read_text()
            assert not (cwd / "node_modules").exists()
            assert not (cwd / ".vuebench-corepack").exists()
            assert not (cwd / ".corepack.env").exists()
            assert (cwd / "src/CounterSummary.vue").read_text() == "candidate source"
            if "vitest run" in command[-1]:
                hidden_name = re.search(
                    r"(--passWithNoTests=false \.vuebench-hidden-[a-z0-9]+)", command[-1]
                ).group(1).split()[-1]
                assert hidden_name.startswith(".vuebench-hidden-")
                assert not (cwd / hidden_name).exists()
                assert f"/workspace/{hidden_name}:ro" in command[-1]
            return subprocess.CompletedProcess(command, 0, self._status_output(command, 0), "")

    verifier = InspectingVerifier()
    result = verifier.run(task_verifier=task.verifier_path, workspace=workspace)
    assert result.passed is True
    assert len(verifier.commands) == 7
    assert (workspace / ".vuebench-hidden").exists()


def test_candidate_symlinks_are_preserved_without_dereferencing(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("host secret")
    (workspace / "link.txt").symlink_to(outside)
    destination = tmp_path / "staging"
    destination.mkdir()

    HiddenVerifier._copy_candidate(workspace, destination)

    copied = destination / "link.txt"
    assert copied.is_symlink()
    assert copied.readlink() == outside


def test_hidden_verifier_rejects_candidate_special_files(tmp_path: Path) -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    os.mkfifo(workspace / "candidate-pipe")

    verifier = SuccessfulHiddenVerifier()
    result = verifier.run(task_verifier=task.verifier_path, workspace=workspace)

    assert result.passed is False
    assert result.infrastructure_error is not None
    assert "unsupported filesystem entry" in result.infrastructure_error
    assert [command[1] for command in verifier.commands] == ["rm"]


@pytest.mark.parametrize(
    "task_id", ["incorrect-watch-source", "reactive-destructure", "shallow-ref"]
)
def test_starters_do_not_disclose_hidden_verifier_path(task_id: str) -> None:
    starter = TASKS_ROOT / "reactivity" / task_id / "starter"
    assert ".vuebench-hidden" not in (starter / ".gitignore").read_text()
    assert ".vuebench-hidden" not in (starter / "vite.config.ts").read_text()


def test_incorrect_watch_source_starter_does_not_disclose_defect() -> None:
    source = (
        TASKS_ROOT
        / "reactivity"
        / "incorrect-watch-source"
        / "starter"
        / "src"
        / "useWatchedCounter.ts"
    ).read_text()
    assert "Intentional bug" not in source
    assert "hidden verifier" not in source


def test_verification_result_parsing_uses_both_exit_codes() -> None:
    result = parse_verification_result(
        tests_returncode=0,
        typecheck_returncode=1,
        tests_output="vitest ok",
        typecheck_output="type error",
    )
    assert result.tests_passed is True
    assert result.typecheck_passed is False
    assert result.passed is False
    assert result.typecheck_output == "type error"


def test_codex_command_is_noninteractive_and_model_is_optional(tmp_path: Path) -> None:
    runner = CodexRunner(executable="codex-test")
    command = runner.command(cwd=tmp_path, source_repo_root=REPO_ROOT)
    assert command[:3] == ["/usr/bin/sandbox-exec", "-p", runner.sandbox_profile(REPO_ROOT)]
    assert command[3:] == [
        "--",
        "codex-test",
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        "--cd",
        str(tmp_path),
        "--sandbox",
        "workspace-write",
        "-c",
        'approval_policy="never"',
        "--ephemeral",
        "--color",
        "never",
    ]
    assert runner.command(cwd=tmp_path, source_repo_root=REPO_ROOT, model="gpt-test")[-2:] == [
        "--model",
        "gpt-test",
    ]
    assert runner.timeout_seconds == DEFAULT_TIMEOUT_SECONDS


def test_codex_refuses_missing_or_unsupported_seatbelt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(CodexSandboxUnavailable, match="unavailable"):
        CodexRunner(sandbox_executable=str(tmp_path / "missing-sandbox")).command(
            cwd=tmp_path, source_repo_root=tmp_path
        )

    monkeypatch.setattr("vuebench.agents.codex.sys.platform", "linux")
    with pytest.raises(CodexSandboxUnavailable, match="refusing to run unisolated"):
        CodexRunner().command(cwd=tmp_path, source_repo_root=tmp_path)


def _initialize_trial_repo(path: Path) -> None:
    path.mkdir()
    (path / "starter.txt").write_text("starter\n")
    subprocess.run(["git", "init", "--quiet"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=path, check=True)
    subprocess.run(["git", "add", "--all"], cwd=path, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "starter"], cwd=path, check=True)


def test_codex_diff_includes_changes_committed_by_agent(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source_root = tmp_path / "benchmark-source"
    _initialize_trial_repo(workspace)
    source_root.mkdir()
    executable = tmp_path / "fake-codex"
    executable.write_text(
        textwrap.dedent(
            """
            #!/bin/sh
            printf 'committed by agent\\n' > committed.txt
            git add committed.txt
            git commit --quiet -m agent-commit
            """
        ).lstrip()
    )
    executable.chmod(0o755)

    result = asyncio.run(
        CodexRunner(executable=str(executable)).run(
            cwd=workspace, source_repo_root=source_root, prompt="fix it"
        )
    )

    assert result.exit_code == 0
    assert "committed.txt" in result.diff
    assert "+committed by agent" in result.diff


def test_codex_seatbelt_blocks_source_checkout_reads(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source_root = tmp_path / "benchmark-source"
    _initialize_trial_repo(workspace)
    source_root.mkdir()
    secret = source_root / "hidden-verifier.ts"
    secret.write_text("hidden assertion\n")
    executable = tmp_path / "probe-codex"
    executable.write_text(
        f"#!/bin/sh\nexec cat '{secret}' > '{workspace / 'probe.txt'}'\n"
    )
    executable.chmod(0o755)

    result = asyncio.run(
        CodexRunner(executable=str(executable), timeout_seconds=5).run(
            cwd=workspace, source_repo_root=source_root, prompt="probe"
        )
    )

    assert result.exit_code != 0
    assert "Operation not permitted" in result.stderr
    assert (workspace / "probe.txt").read_text() == ""


def test_codex_timeout_terminates_process_group(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source_root = tmp_path / "benchmark-source"
    _initialize_trial_repo(workspace)
    source_root.mkdir()
    executable = tmp_path / "hanging-codex"
    executable.write_text("#!/bin/sh\nsleep 30 &\nwait\n")
    executable.chmod(0o755)

    started = time.monotonic()
    result = asyncio.run(
        CodexRunner(
            executable=str(executable), timeout_seconds=0.1, drain_timeout_seconds=0.1
        ).run(cwd=workspace, source_repo_root=source_root, prompt="hang")
    )

    assert time.monotonic() - started < 3
    assert "timed out" in result.stderr


class FakeAgent:
    async def run(
        self,
        *,
        cwd: Path,
        source_repo_root: Path,
        prompt: str,
        model: str | None = None,
    ) -> AgentResult:
        assert not (cwd / ".vuebench-hidden").exists()
        assert source_repo_root == REPO_ROOT
        assert str(REPO_ROOT) not in prompt
        return AgentResult(
            exit_code=0,
            stdout="fake",
            stderr="",
            diff="",
            duration_seconds=0.01,
        )


class FailingAgent:
    async def run(
        self,
        *,
        cwd: Path,
        source_repo_root: Path,
        prompt: str,
        model: str | None = None,
    ) -> AgentResult:
        raise RuntimeError("codex unavailable")


def test_benchmark_uses_fake_agent_without_invoking_codex() -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    benchmark = Benchmark(
        agent=FakeAgent(),
        workspace_manager=NoInstallWorkspaceManager(),
        verifier=SuccessfulHiddenVerifier(),
    )
    results = asyncio.run(benchmark.run([task]))
    result = results[0]
    assert result.agent.stdout == "fake"
    assert result.verification.passed is True
    assert benchmark.last_report is not None
    report_case = benchmark.last_report.cases[0]
    assert report_case.assertions["passed"].value is True
    assert report_case.metadata == {"category": "reactivity", "difficulty": "easy"}


def test_benchmark_forwards_task_runtime_to_hidden_verifier() -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    calls: dict[str, object] = {}

    class RuntimeVerifier(HiddenVerifier):
        def run(self, **kwargs: object) -> object:
            calls.update(kwargs)
            from vuebench.models import VerificationResult

            return VerificationResult(
                tests_passed=True,
                typecheck_passed=True,
                tests_output="",
                typecheck_output="",
                passed=True,
            )

    benchmark = Benchmark(
        agent=FakeAgent(),
        workspace_manager=NoInstallWorkspaceManager(),
        verifier=RuntimeVerifier(),
    )
    asyncio.run(benchmark.run([task]))
    assert calls["node"] == task.runtime.node
    assert calls["package_manager"] == task.runtime.package_manager


def test_benchmark_surfaces_verification_infrastructure_failure_as_execution_error() -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")

    class InfrastructureVerifier(HiddenVerifier):
        def run(self, **kwargs: object) -> VerificationResult:
            return VerificationResult(
                tests_passed=False,
                typecheck_passed=False,
                tests_output="sbx unavailable",
                typecheck_output="sbx unavailable",
                passed=False,
                infrastructure_error="sbx unavailable",
            )

    benchmark = Benchmark(
        agent=FakeAgent(),
        workspace_manager=NoInstallWorkspaceManager(),
        verifier=InfrastructureVerifier(),
    )
    with pytest.raises(BenchmarkExecutionError, match="sbx unavailable"):
        asyncio.run(benchmark.run([task]))
    assert benchmark.last_report is not None
    assert benchmark.last_report.cases == []
    assert [failure.name for failure in benchmark.last_report.failures] == [task.id]


def test_benchmark_surfaces_case_execution_failures() -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    benchmark = Benchmark(
        agent=FailingAgent(),
        workspace_manager=NoInstallWorkspaceManager(),
        verifier=SuccessfulHiddenVerifier(),
    )

    with pytest.raises(BenchmarkExecutionError, match="reactive-destructure"):
        asyncio.run(benchmark.run([task]))
    assert benchmark.last_report is not None
    assert benchmark.last_report.cases == []
    assert [failure.name for failure in benchmark.last_report.failures] == [task.id]


def test_cli_reports_case_execution_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")

    class FailingBenchmark:
        def __init__(self, *, agent: object) -> None:
            pass

        async def run(self, tasks: list[object], *, model: str | None = None) -> list[object]:
            raise BenchmarkExecutionError(
                [SimpleNamespace(name=tasks[0].id, error_message="codex unavailable")]
            )

    monkeypatch.setattr(cli, "Benchmark", FailingBenchmark)
    monkeypatch.setattr(cli, "discover_tasks", lambda _: [task])
    monkeypatch.setattr(sys, "argv", ["vuebench", "run", "--task", task.id])

    with pytest.raises(SystemExit, match="Benchmark failed:.*reactive-destructure"):
        cli.main()


def test_cli_defaults_to_run_without_a_command() -> None:
    args = cli.build_parser().parse_args([])

    assert args.command == "run"
    assert args.task is None
    assert args.model is None
    assert args.timeout == DEFAULT_TIMEOUT_SECONDS
    assert args.tasks_root == cli.default_tasks_root()


def test_cli_accepts_run_options_without_a_command(tmp_path: Path) -> None:
    args = cli.build_parser().parse_args(
        [
            "--task",
            "reactive-destructure",
            "--model",
            "gpt-test",
            "--timeout",
            "12",
            "--tasks-root",
            str(tmp_path),
        ]
    )

    assert args.command == "run"
    assert args.task == "reactive-destructure"
    assert args.model == "gpt-test"
    assert args.timeout == 12
    assert args.tasks_root == tmp_path


def test_cli_main_runs_with_no_command(monkeypatch: pytest.MonkeyPatch) -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    calls: dict[str, object] = {}

    class SuccessfulBenchmark:
        def __init__(self, *, agent: object) -> None:
            calls["agent"] = agent

        async def run(self, tasks: list[object], *, model: str | None = None) -> list[object]:
            calls["tasks"] = tasks
            calls["model"] = model
            return [
                SimpleNamespace(
                    task_id=task.id,
                    agent=SimpleNamespace(exit_code=0, duration_seconds=0.01),
                    verification=SimpleNamespace(
                        tests_passed=True, typecheck_passed=True, passed=True
                    ),
                )
            ]

    monkeypatch.setattr(cli, "Benchmark", SuccessfulBenchmark)
    monkeypatch.setattr(cli, "discover_tasks", lambda _: [task])
    monkeypatch.setattr(sys, "argv", ["vuebench"])

    cli.main()

    assert calls["tasks"] == [task]
    assert calls["model"] is None


def test_deterministic_evaluator_reads_only_verification() -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    from vuebench.models import BenchmarkResult, VerificationResult

    output = BenchmarkResult(
        task_id=task.id,
        task_title=task.title,
        category=task.category,
        difficulty=task.difficulty,
        agent=AgentResult(exit_code=0, stdout="", stderr="", diff="", duration_seconds=1),
        verification=VerificationResult(
            tests_passed=True,
            typecheck_passed=True,
            tests_output="",
            typecheck_output="",
            passed=True,
        ),
    )
    context = EvaluatorContext(
        name=task.id,
        inputs=None,
        metadata=None,
        expected_output=None,
        output=output,
        duration=1,
        _span_tree=None,
        attributes={},
        metrics={},
    )
    evaluations = DeterministicEvaluator().evaluate(context)
    assert evaluations["passed"].value is True
