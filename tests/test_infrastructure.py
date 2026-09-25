import asyncio
import json
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
from vuebench.agents import ClaudeRunner, GrokRunner, OpenCodeRunner, OriRunner, create_agent_runner
from vuebench.agents.codex import (
    DEFAULT_TIMEOUT_SECONDS,
    CodexRunner,
    CodexSandboxUnavailable,
)
from vuebench.benchmark import Benchmark, BenchmarkExecutionError, DeterministicEvaluator
from vuebench.models import AgentResult, BenchmarkResult, RuntimeConfig, VerificationResult
from vuebench.tasks.discovery import discover_tasks, load_task
from vuebench.tasks.workspace import WorkspaceManager
from vuebench.verification.runner import (
    HiddenVerifier,
    VerifierUnavailable,
    parse_verification_result,
)

REPO_ROOT = Path(__file__).parents[1]
TASKS_ROOT = REPO_ROOT / "tasks"


def test_discovery_loads_all_tasks() -> None:
    tasks = discover_tasks(TASKS_ROOT)
    assert [task.id for task in tasks] == [
        "accessible-control",
        "directive-cleanup",
        "conditional-editor-focus",
        "custom-v-model",
        "keep-alive-draft",
        "list-identity",
        "prop-mutation",
        "scoped-slots",
        "search-field-sync",
        "wrapper-attrs",
        "computed-side-effects",
        "derived-totals",
        "incorrect-watch-source",
        "reactive-destructure",
        "shallow-ref",
        "stale-async-search",
        "cart-shared-state",
    ]
    assert all(task.instruction for task in tasks)
    assert all(task.starter_path.is_dir() for task in tasks)


@pytest.mark.parametrize(
    ("task_id", "api"),
    [
        ("search-field-sync", "defineModel"),
        ("conditional-editor-focus", "useTemplateRef"),
    ],
)
def test_new_api_tasks_do_not_name_the_solution_in_agent_material(task_id: str, api: str) -> None:
    task = load_task(TASKS_ROOT / "components" / task_id / "task.yaml")
    assert api.lower() not in f"{task.path} {task.title} {task.instruction}".lower()
    for path in task.starter_path.rglob("*"):
        if path.is_file() and "node_modules" not in path.parts:
            assert api.lower() not in path.read_text().lower()


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
        return self._command_result(command)

    def _command_result(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[1:3] == ["diagnose", "--json"]:
            return subprocess.CompletedProcess(
                command,
                0,
                '{"checks": [], "summary": {"fail": 0}}',
                "",
            )
        if command[1:3] == ["ls", "--json"]:
            return subprocess.CompletedProcess(
                command,
                0,
                '{"sandboxes": [{"name": "vuebench-verifier", "status": "running"}]}',
                "",
            )
        marker = re.search(r"printf 'VUEBENCH_STATUS:([^:]+):%s", command[-1])
        output = "ok"
        if marker:
            output += f"\nVUEBENCH_STATUS:{marker.group(1)}:0"
        return subprocess.CompletedProcess(command, 0, output, "")

    @staticmethod
    def _status_output(command: list[str], status: int) -> str:
        marker = re.search(r"printf 'VUEBENCH_STATUS:([^:]+):%s", command[-1])
        return f"ok\nVUEBENCH_STATUS:{marker.group(1)}:{status}" if marker else "ok"


def test_hidden_verifier_uses_persistent_sandbox_and_disposable_run_state(
    tmp_path: Path,
) -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    verifier = SuccessfulHiddenVerifier()
    result = verifier.run(task_verifier=task.verifier_path, workspace=workspace)
    assert result.passed is True
    assert len(verifier.commands) == 12
    (
        listed,
        probe,
        prepare,
        copy,
        injection,
        tool_volume,
        dependency_volume,
        install,
        typecheck,
        tests,
        volume_cleanup,
        directory_cleanup,
    ) = verifier.commands
    assert listed == ["fake-sbx", "ls", "--json"]
    assert probe == ["fake-sbx", "exec", "vuebench-verifier", "true"]
    assert prepare[:5] == ["fake-sbx", "exec", "vuebench-verifier", "mkdir", "-p"]
    assert prepare[-1].startswith("/tmp/vuebench-runs/")
    assert copy[:2] == ["fake-sbx", "cp"]
    assert copy[-1].startswith("vuebench-verifier:/tmp/vuebench-runs/")
    sandbox_name = "vuebench-verifier"
    assert injection[:5] == ["fake-sbx", "exec", sandbox_name, "sh", "-lc"]
    assert injection[-1].startswith("mkdir -p ")
    assert tool_volume[:6] == [
        "fake-sbx",
        "exec",
        sandbox_name,
        "docker",
        "volume",
        "create",
    ]
    assert tool_volume[-1].startswith("vuebench-tools-")
    assert dependency_volume[:6] == tool_volume[:6]
    assert dependency_volume[-1].startswith("vuebench-deps-")
    assert install[:4] == ["fake-sbx", "exec", sandbox_name, "docker"]
    assert "npm install --prefix /vuebench-tools --ignore-scripts corepack@0.33.0" in install[-1]
    assert "--store-dir /vuebench-tools/store" in install[-1]
    assert any(argument.endswith(":/workspace/node_modules") for argument in install)
    assert typecheck[:5] == ["fake-sbx", "exec", sandbox_name, "sh", "-lc"]
    assert "docker run --rm --network none" in typecheck[-1]
    assert ":ro" in typecheck[-1]
    assert ":/workspace/node_modules:ro" in typecheck[-1]
    assert "--tmpfs /workspace/node_modules/.vite" in typecheck[-1]
    assert "--tmpfs /workspace/node_modules/.vite-temp" in typecheck[-1]
    assert "node:24-bookworm" in typecheck[-1]
    assert "vue-tsc" in typecheck[-1]
    assert "VUEBENCH_STATUS:" in typecheck[-1]
    assert tests[:5] == ["fake-sbx", "exec", sandbox_name, "sh", "-lc"]
    assert "vitest run" in tests[-1]
    assert "VUEBENCH_STATUS:" in tests[-1]
    assert volume_cleanup[3:7] == ["docker", "volume", "rm", "--force"]
    assert len(volume_cleanup) == 9
    assert volume_cleanup[-2].startswith("vuebench-tools-")
    assert volume_cleanup[-1].startswith("vuebench-deps-")
    assert directory_cleanup[:7] == [
        "fake-sbx",
        "exec",
        sandbox_name,
        "sudo",
        "rm",
        "-rf",
        "--",
    ]
    assert not any(command[1] == "create" for command in verifier.commands)
    assert not any(command[1:3] == ["rm", "--force"] for command in verifier.commands)
    assert not (workspace / ".vuebench-hidden").exists()


def test_hidden_verifier_reuses_sandbox_with_unique_run_roots_and_runtime_node(
    tmp_path: Path,
) -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    verifier = SuccessfulHiddenVerifier()
    verifier.run(task_verifier=task.verifier_path, workspace=workspace, node=24)
    verifier.run(task_verifier=task.verifier_path, workspace=workspace, node=25)

    roots = [command[-1] for command in verifier.commands if command[3:5] == ["mkdir", "-p"]]
    assert len(roots) == 2
    assert len(set(roots)) == 2
    assert sum(command[1:3] == ["diagnose", "--json"] for command in verifier.commands) == 0
    assert sum(command[1:3] == ["ls", "--json"] for command in verifier.commands) == 2
    assert any("node:24-bookworm" in command[-1] for command in verifier.commands)
    assert any("node:25-bookworm" in command[-1] for command in verifier.commands)


def test_hidden_verifier_preflight_creates_mountless_sandbox(tmp_path: Path) -> None:
    class MissingSandboxVerifier(SuccessfulHiddenVerifier):
        def _command_result(self, command: list[str]) -> subprocess.CompletedProcess[str]:
            if command[1:3] == ["ls", "--json"]:
                return subprocess.CompletedProcess(command, 0, '{"sandboxes": []}', "")
            return super()._command_result(command)

    verifier = MissingSandboxVerifier()
    verifier.preflight(cwd=tmp_path)

    create = verifier.commands[2]
    assert create == [
        "fake-sbx",
        "create",
        "--pull",
        "missing",
        "--cpus",
        "2",
        "--memory",
        "4g",
        "--quiet",
        "--name",
        "vuebench-verifier",
        "shell",
    ]
    assert "--clone" not in create
    assert verifier.commands[3] == ["fake-sbx", "exec", "vuebench-verifier", "true"]


def test_hidden_verifier_preflight_restarts_stopped_sandbox(tmp_path: Path) -> None:
    class StoppedSandboxVerifier(SuccessfulHiddenVerifier):
        def _command_result(self, command: list[str]) -> subprocess.CompletedProcess[str]:
            if command[1:3] == ["ls", "--json"]:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    '{"sandboxes": [{"name": "vuebench-verifier", "status": "stopped"}]}',
                    "",
                )
            return super()._command_result(command)

    verifier = StoppedSandboxVerifier()
    verifier.preflight(cwd=tmp_path)

    assert verifier.commands[2] == [
        "fake-sbx",
        "run",
        "--detached",
        "--name",
        "vuebench-verifier",
    ]
    assert verifier.commands[3] == ["fake-sbx", "exec", "vuebench-verifier", "true"]


def test_hidden_verifier_recreates_stale_sandbox_record(tmp_path: Path) -> None:
    class StaleSandboxVerifier(SuccessfulHiddenVerifier):
        def _command_result(self, command: list[str]) -> subprocess.CompletedProcess[str]:
            if command[1:3] == ["ls", "--json"]:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    '{"sandboxes": [{"name": "vuebench-verifier", "status": "stopped"}]}',
                    "",
                )
            if command[1] == "run":
                return subprocess.CompletedProcess(
                    command, 1, "", 'container missing before start: "vuebench-verifier"'
                )
            return super()._command_result(command)

    verifier = StaleSandboxVerifier()
    verifier.preflight(cwd=tmp_path)

    assert verifier.commands[3] == [
        "fake-sbx",
        "rm",
        "--force",
        "vuebench-verifier",
    ]
    assert verifier.commands[4][1] == "create"
    assert "--clone" not in verifier.commands[4]
    assert verifier.commands[5] == ["fake-sbx", "exec", "vuebench-verifier", "true"]


def test_hidden_verifier_preflight_fails_fast_on_diagnostics(tmp_path: Path) -> None:
    class FailedDiagnosticsVerifier(SuccessfulHiddenVerifier):
        def _command_result(self, command: list[str]) -> subprocess.CompletedProcess[str]:
            if command[1:3] == ["ls", "--json"]:
                return subprocess.CompletedProcess(command, 0, '{"sandboxes": []}', "")
            if command[1:3] == ["diagnose", "--json"]:
                return subprocess.CompletedProcess(
                    command,
                    1,
                    '{"checks": [{"name": "Daemon diagnostics", "status": "fail", '
                    '"message": "check timed out"}], "summary": {"fail": 1}}',
                    "",
                )
            return super()._command_result(command)

    verifier = FailedDiagnosticsVerifier()
    with pytest.raises(VerifierUnavailable, match="Daemon diagnostics: check timed out"):
        verifier.preflight(cwd=tmp_path)

    assert verifier.commands == [
        ["fake-sbx", "ls", "--json"],
        ["fake-sbx", "diagnose", "--json"],
    ]


def test_hidden_verifier_fails_before_transfer_on_preflight_timeout(tmp_path: Path) -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class TimeoutVerifier(SuccessfulHiddenVerifier):
        def _command_result(self, command: list[str]) -> subprocess.CompletedProcess[str]:
            if command[-1] == "true":
                raise subprocess.TimeoutExpired(command, 1)
            return super()._command_result(command)

    verifier = TimeoutVerifier()
    result = verifier.run(task_verifier=task.verifier_path, workspace=workspace)
    assert result.passed is False
    assert result.infrastructure_error is not None
    assert "timed out" in result.infrastructure_error
    assert [command[1] for command in verifier.commands] == ["ls", "exec"]


def test_hidden_verifier_keeps_test_failures_distinct_from_sbx_failures(tmp_path: Path) -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class TestFailureVerifier(SuccessfulHiddenVerifier):
        def _command_result(self, command: list[str]) -> subprocess.CompletedProcess[str]:
            if "vitest run" in command[-1]:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    self._status_output(command, 1).replace("ok", "assertion failed"),
                    "",
                )
            return super()._command_result(command)

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
        def _command_result(self, command: list[str]) -> subprocess.CompletedProcess[str]:
            if "vitest run" in command[-1]:
                return subprocess.CompletedProcess(command, 1, "docker daemon failed", "")
            return super()._command_result(command)

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
        def _command_result(self, command: list[str]) -> subprocess.CompletedProcess[str]:
            if "vitest run" in command[-1] and marker:
                return subprocess.CompletedProcess(command, 0, f"ok\n{marker.strip()}", "")
            if "vitest run" in command[-1]:
                return subprocess.CompletedProcess(command, 0, "ok", "")
            return super()._command_result(command)

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
        def _command_result(self, command: list[str]) -> subprocess.CompletedProcess[str]:
            if "vue-tsc" in command[-1]:
                return subprocess.CompletedProcess(command, 0, self._status_output(command, 2), "")
            return super()._command_result(command)

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
        def _command_result(self, command: list[str]) -> subprocess.CompletedProcess[str]:
            if "vue-tsc" in command[-1]:
                return subprocess.CompletedProcess(
                    command, 0, self._status_output(command, docker_status), ""
                )
            return super()._command_result(command)

    result = ContainerFailureVerifier().run(task_verifier=task.verifier_path, workspace=workspace)
    assert result.passed is False
    assert result.infrastructure_error is not None


def test_hidden_verifier_reports_cleanup_failure(tmp_path: Path) -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class CleanupFailureVerifier(SuccessfulHiddenVerifier):
        def _command_result(self, command: list[str]) -> subprocess.CompletedProcess[str]:
            if command[3:7] == ["sudo", "rm", "-rf", "--"]:
                return subprocess.CompletedProcess(command, 1, "", "permission denied")
            return super()._command_result(command)

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
            if command[1] not in {"diagnose", "ls"} and command[-1] != "true":
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
                hidden_name = (
                    re.search(r"(--passWithNoTests=false \.vuebench-hidden-[a-z0-9]+)", command[-1])
                    .group(1)
                    .split()[-1]
                )
                assert hidden_name.startswith(".vuebench-hidden-")
                assert not (cwd / hidden_name).exists()
                assert f"/workspace/{hidden_name}:ro" in command[-1]
            return self._command_result(command)

    verifier = InspectingVerifier()
    result = verifier.run(task_verifier=task.verifier_path, workspace=workspace)
    assert result.passed is True
    assert len(verifier.commands) == 12
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
    assert [command[1] for command in verifier.commands] == ["ls", "exec"]


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
    assert command[:3] == [
        "/usr/bin/sandbox-exec",
        "-p",
        runner.sandbox_profile(REPO_ROOT, tmp_path),
    ]
    assert "require-not" in command[2]
    assert command[3:] == [
        "--",
        "codex-test",
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        "--cd",
        str(tmp_path),
        "--sandbox",
        "danger-full-access",
        "-c",
        'approval_policy="never"',
        "--ephemeral",
        "--color",
        "never",
    ]
    configured_command = runner.command(
        cwd=tmp_path,
        source_repo_root=REPO_ROOT,
        model="gpt-test",
        effort="high",
    )
    assert configured_command[-4:] == [
        "-c",
        'model_reasoning_effort="high"',
        "--model",
        "gpt-test",
    ]
    assert runner.timeout_seconds == DEFAULT_TIMEOUT_SECONDS


def test_codex_uses_disposable_home_for_state_and_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_home = tmp_path / "user-codex"
    user_home.mkdir()
    (user_home / "auth.json").write_text('{"token":"test"}')
    monkeypatch.setenv("CODEX_HOME", str(user_home))
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    environment = CodexRunner().process_environment(scratch=scratch)
    codex_home = scratch / "codex"
    auth_copy = codex_home / "auth.json"

    assert environment["CODEX_HOME"] == str(codex_home)
    assert environment["TMPDIR"] == str(scratch)
    assert auth_copy.read_text() == '{"token":"test"}'
    assert auth_copy.stat().st_mode & 0o777 == 0o600
    assert (user_home / "auth.json").read_text() == '{"token":"test"}'


def test_native_agent_commands_are_noninteractive_and_model_aware(tmp_path: Path) -> None:
    claude = ClaudeRunner(executable="claude-test")
    claude_command = claude.command(
        cwd=tmp_path,
        source_repo_root=REPO_ROOT,
        model="sonnet",
        effort="high",
        prompt="fix it",
    )
    assert claude_command[-5:] == ["text", "--effort", "high", "--model", "sonnet"]
    assert "--safe-mode" in claude_command
    assert "--no-session-persistence" in claude_command

    opencode = OpenCodeRunner(executable="opencode-test")
    opencode_command = opencode.command(
        cwd=tmp_path,
        source_repo_root=REPO_ROOT,
        model="openai/gpt-test",
        effort="high",
        prompt="fix it",
    )
    assert opencode_command[-5:] == [
        "--variant",
        "high",
        "--model",
        "openai/gpt-test",
        "fix it",
    ]
    assert "--pure" in opencode_command
    assert "--auto" in opencode_command

    ori = OriRunner(executable="ori-test")
    ori_command = ori.command(
        cwd=tmp_path,
        source_repo_root=REPO_ROOT,
        model="openai/gpt-test",
        effort="high",
        prompt="fix it",
    )
    inner = ori_command[4:]
    assert inner == [
        "ori-test",
        "code",
        "--approvals",
        "self-drive",
        "--output",
        "text",
        "--reasoning-effort",
        "high",
        "--model",
        "openai/gpt-test",
        "--prompt",
        "fix it",
    ]
    assert ori.prompt_input("fix it") is None
    ori_environment = ori.process_environment(scratch=tmp_path)
    assert ori_environment["HOME"] == str(tmp_path)
    assert ori_environment["TMPDIR"] == str(tmp_path)
    assert ori_environment["BUN_TMPDIR"] == str(tmp_path)
    assert ori_environment["BUN_INSTALL_CACHE_DIR"] == str(tmp_path / "bun-cache")

    auth_path = tmp_path / "grok-auth.json"
    auth_path.write_text('{"token":"test"}')
    grok_scratch = tmp_path / "grok-scratch"
    grok_scratch.mkdir()
    grok = GrokRunner(executable="grok-test", auth_path=auth_path)
    grok_command = grok.command(
        cwd=tmp_path,
        source_repo_root=REPO_ROOT,
        model="grok-test-model",
        effort="high",
        prompt="fix it",
    )
    assert grok_command[-14:] == [
        "grok-test",
        "--cwd",
        str(tmp_path),
        "--always-approve",
        "--no-alt-screen",
        "--no-plan",
        "--output-format",
        "plain",
        "--reasoning-effort",
        "high",
        "--model",
        "grok-test-model",
        "--single",
        "fix it",
    ]
    assert grok.prompt_input("fix it") is None
    grok_environment = grok.process_environment(scratch=grok_scratch)
    scratch_auth = Path(grok_environment["GROK_AUTH_PATH"])
    assert grok_environment["HOME"] == str(grok_scratch)
    assert Path(grok_environment["GROK_CONFIG_PATH"]).read_text() == ""
    assert grok_environment["GROK_DISABLE_AUTOUPDATER"] == "1"
    assert scratch_auth.read_text() == '{"token":"test"}'
    assert scratch_auth.stat().st_mode & 0o777 == 0o600

    assert isinstance(create_agent_runner("claude", timeout_seconds=12), ClaudeRunner)
    assert isinstance(create_agent_runner("grok", timeout_seconds=12), GrokRunner)


def test_native_agent_profile_blocks_writes_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source = tmp_path / "source"
    scratch = tmp_path / "scratch"
    outside = tmp_path / "outside"
    workspace.mkdir()
    source.mkdir()
    scratch.mkdir()
    outside.mkdir()
    profile = CodexRunner.sandbox_profile(source, workspace, scratch)

    result = subprocess.run(
        [
            "/usr/bin/sandbox-exec",
            "-p",
            profile,
            "--",
            "/bin/sh",
            "-c",
            f"printf allowed > '{workspace / 'file'}'; "
            f"printf temporary > '{scratch / 'file'}'; "
            f"printf blocked > '{outside / 'file'}'",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert (workspace / "file").read_text() == "allowed"
    assert (scratch / "file").read_text() == "temporary"
    assert not (outside / "file").exists()


def test_codex_profile_allows_pty_inside_outer_sandbox(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source = tmp_path / "source"
    scratch = tmp_path / "scratch"
    workspace.mkdir()
    source.mkdir()
    scratch.mkdir()

    result = subprocess.run(
        [
            "/usr/bin/sandbox-exec",
            "-p",
            CodexRunner.sandbox_profile(source, workspace, scratch),
            "--",
            "/usr/bin/python3",
            "-c",
            "import os, pty; master, slave = pty.openpty(); "
            "print(os.ttyname(slave)); os.close(master); os.close(slave)",
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().startswith("/dev/ttys")


def test_codex_refuses_missing_or_unsupported_seatbelt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(CodexSandboxUnavailable, match="unavailable"):
        CodexRunner(sandbox_executable=str(tmp_path / "missing-sandbox")).command(
            cwd=tmp_path, source_repo_root=tmp_path
        )

    monkeypatch.setattr("vuebench.agents.native.sys.platform", "linux")
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
    assert ".vuebench-tmp" not in result.diff


def test_native_agent_uses_runner_scratch_outside_candidate_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source_root = tmp_path / "benchmark-source"
    _initialize_trial_repo(workspace)
    source_root.mkdir()
    executable = tmp_path / "fake-codex"
    executable.write_text(
        "#!/bin/sh\nprintf '%s' \"$TMPDIR\" > runner-tmpdir.txt\n"
        'printf scratch > "$TMPDIR/probe.txt"\n'
    )
    executable.chmod(0o755)

    result = asyncio.run(
        CodexRunner(executable=str(executable)).run(
            cwd=workspace, source_repo_root=source_root, prompt="fix it"
        )
    )

    scratch_path = Path((workspace / "runner-tmpdir.txt").read_text())
    assert result.exit_code == 0
    assert scratch_path.parent != workspace
    assert scratch_path.name.startswith("vuebench-agent-")
    assert not scratch_path.exists()
    assert ".vuebench-tmp" not in result.diff


def test_codex_seatbelt_blocks_source_checkout_reads(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source_root = tmp_path / "benchmark-source"
    _initialize_trial_repo(workspace)
    source_root.mkdir()
    secret = source_root / "hidden-verifier.ts"
    secret.write_text("hidden assertion\n")
    executable = tmp_path / "probe-codex"
    executable.write_text(f"#!/bin/sh\nexec cat '{secret}' > '{workspace / 'probe.txt'}'\n")
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
        CodexRunner(executable=str(executable), timeout_seconds=0.1, drain_timeout_seconds=0.1).run(
            cwd=workspace, source_repo_root=source_root, prompt="hang"
        )
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
        effort: str | None = None,
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
        effort: str | None = None,
    ) -> AgentResult:
        raise RuntimeError("codex unavailable")


class NonZeroAgent(FakeAgent):
    async def run(self, **kwargs: object) -> AgentResult:
        return AgentResult(
            exit_code=1,
            stdout="additional context",
            stderr="agent runtime failed",
            diff="",
            duration_seconds=0.01,
        )


def test_benchmark_uses_fake_agent_without_invoking_codex() -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    benchmark = Benchmark(
        agent=FakeAgent(),
        workspace_manager=NoInstallWorkspaceManager(),
        verifier=SuccessfulHiddenVerifier(),
    )
    results = asyncio.run(benchmark.run([task], model="test-model", effort="high"))
    result = results[0]
    assert result.agent.stdout == "fake"
    assert result.model == "test-model"
    assert result.effort == "high"
    assert result.verification.passed is True
    assert benchmark.last_report is not None
    report_case = benchmark.last_report.cases[0]
    assert report_case.assertions["passed"].value is True
    assert report_case.metadata == {"category": "reactivity", "difficulty": "easy"}


def test_benchmark_reports_progress_and_preflights_before_agent() -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    events: list[str] = []

    class OrderedVerifier(SuccessfulHiddenVerifier):
        def preflight(self, *, cwd: Path | None = None) -> None:
            events.append("preflight")
            super().preflight(cwd=cwd)

        def run(self, **kwargs: object) -> VerificationResult:
            events.append("verify")
            return super().run(**kwargs)

    class OrderedAgent(FakeAgent):
        async def run(self, **kwargs: object) -> AgentResult:
            events.append("agent")
            return await super().run(**kwargs)

    benchmark = Benchmark(
        agent=OrderedAgent(),
        agent_name="fake",
        workspace_manager=NoInstallWorkspaceManager(),
        verifier=OrderedVerifier(),
        progress=lambda message: events.append(message),
    )
    asyncio.run(benchmark.run([task]))

    assert events.index("preflight") < events.index("agent") < events.index("verify")
    assert any("running fake" in event for event in events)
    assert any("verifying in SBX" in event for event in events)


def test_benchmark_forwards_task_runtime_to_hidden_verifier() -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    calls: dict[str, object] = {}

    class RuntimeVerifier(HiddenVerifier):
        def preflight(self, *, cwd: Path | None = None) -> None:
            pass

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
        def preflight(self, *, cwd: Path | None = None) -> None:
            pass

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


def test_benchmark_does_not_grade_a_nonzero_agent_exit() -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")

    class UnexpectedVerifier(SuccessfulHiddenVerifier):
        def run(self, **kwargs: object) -> VerificationResult:
            raise AssertionError("verification must not run after an agent process failure")

    benchmark = Benchmark(
        agent=NonZeroAgent(),
        agent_name="test-agent",
        workspace_manager=NoInstallWorkspaceManager(),
        verifier=UnexpectedVerifier(),
    )

    with pytest.raises(
        BenchmarkExecutionError,
        match=(
            "test-agent exited with status 1: stderr: agent runtime failed; "
            "stdout: additional context"
        ),
    ):
        asyncio.run(benchmark.run([task]))


def test_cli_reports_case_execution_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")

    class FailingBenchmark:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def run(
            self,
            tasks: list[object],
            *,
            model: str | None = None,
            effort: str | None = None,
        ) -> list[object]:
            raise BenchmarkExecutionError(
                [SimpleNamespace(name=tasks[0].id, error_message="codex unavailable")]
            )

    monkeypatch.setattr(cli, "Benchmark", FailingBenchmark)
    monkeypatch.setattr(cli, "discover_tasks", lambda _: [task])
    monkeypatch.setattr(sys, "argv", ["vuebench", "run", "--task", task.id, "--no-save"])

    with pytest.raises(SystemExit, match="Benchmark failed:.*reactive-destructure"):
        cli.main()


def test_cli_defaults_to_run_without_a_command() -> None:
    args = cli.build_parser().parse_args([])

    assert args.command == "run"
    assert args.task is None
    assert args.model is None
    assert args.effort is None
    assert args.timeout == DEFAULT_TIMEOUT_SECONDS
    assert args.tasks_root == cli.default_tasks_root()


def test_cli_accepts_run_options_without_a_command(tmp_path: Path) -> None:
    args = cli.build_parser().parse_args(
        [
            "--task",
            "reactive-destructure",
            "--model",
            "gpt-test",
            "--effort",
            "high",
            "--timeout",
            "12",
            "--tasks-root",
            str(tmp_path),
        ]
    )

    assert args.command == "run"
    assert args.task == "reactive-destructure"
    assert args.model == "gpt-test"
    assert args.effort == "high"
    assert args.timeout == 12
    assert args.tasks_root == tmp_path


def test_cli_accepts_agent_and_verifier_management_commands() -> None:
    run_args = cli.build_parser().parse_args(
        ["run", "--agent", "ori", "--model", "openai/gpt", "--effort", "xhigh"]
    )
    verifier_args = cli.build_parser().parse_args(["verifier", "status", "--name", "vuebench-test"])

    assert run_args.command == "run"
    assert run_args.agent == "ori"
    assert run_args.model == "openai/gpt"
    assert run_args.effort == "xhigh"
    assert verifier_args.command == "verifier"
    assert verifier_args.action == "status"
    assert verifier_args.name == "vuebench-test"


def test_json_result_document_is_structured_and_atomic(tmp_path: Path) -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    result = BenchmarkResult(
        task_id=task.id,
        task_title=task.title,
        category=task.category,
        difficulty=task.difficulty,
        agent_name="codex",
        model="gpt-test",
        effort="high",
        agent=AgentResult(exit_code=0, stdout="", stderr="", diff="", duration_seconds=1),
        verification=VerificationResult(
            tests_passed=True,
            typecheck_passed=True,
            tests_output="ok",
            typecheck_output="ok",
            passed=True,
        ),
    )
    started = cli.datetime.now(cli.UTC)
    output = tmp_path / "nested" / "result.json"

    cli._write_json(
        output,
        cli._result_payload(
            started=started,
            agent="codex",
            model="gpt-test",
            effort="high",
            results=[result],
        ),
    )

    payload = json.loads(output.read_text())
    assert payload["schema_version"] == 1
    assert payload["status"] == "completed"
    assert payload["effort"] == "high"
    assert payload["results"][0]["effort"] == "high"
    assert payload["results"][0]["task_id"] == task.id
    assert not (output.parent / f".{output.name}.tmp").exists()


def test_cli_main_runs_with_no_command(monkeypatch: pytest.MonkeyPatch) -> None:
    task = load_task(TASKS_ROOT / "reactivity" / "reactive-destructure" / "task.yaml")
    calls: dict[str, object] = {}

    class SuccessfulBenchmark:
        def __init__(self, **kwargs: object) -> None:
            calls.update(kwargs)

        async def run(
            self,
            tasks: list[object],
            *,
            model: str | None = None,
            effort: str | None = None,
        ) -> list[object]:
            calls["tasks"] = tasks
            calls["model"] = model
            calls["effort"] = effort
            return [
                SimpleNamespace(
                    task_id=task.id,
                    agent_name="codex",
                    agent=SimpleNamespace(exit_code=0, duration_seconds=0.01),
                    verification=SimpleNamespace(
                        tests_passed=True, typecheck_passed=True, passed=True
                    ),
                )
            ]

    monkeypatch.setattr(cli, "Benchmark", SuccessfulBenchmark)
    monkeypatch.setattr(cli, "discover_tasks", lambda _: [task])
    monkeypatch.setattr(sys, "argv", ["vuebench", "--no-save"])

    cli.main()

    assert calls["tasks"] == [task]
    assert calls["model"] is None
    assert calls["effort"] is None


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
