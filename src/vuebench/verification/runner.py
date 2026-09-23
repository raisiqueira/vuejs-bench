import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from vuebench.models import VerificationResult

COREPACK_ENV = "COREPACK_ENV_FILE=0"
COREPACK_HOME = "/vuebench-tools/corepack"
COREPACK_VERSION = "corepack@0.33.0"
PINNED_PNPM = "pnpm@11.1.1"
DEFAULT_NODE_VERSION = 24
DEFAULT_COMMAND_TIMEOUT_SECONDS = 300.0
DEFAULT_SANDBOX_NAME = "vuebench-verifier"
DEFAULT_SANDBOX_CPUS = 2
DEFAULT_SANDBOX_MEMORY = "4g"
RUNS_ROOT = PurePosixPath("/tmp/vuebench-runs")
STATUS_PREFIX = "VUEBENCH_STATUS:"


def parse_verification_result(
    *,
    tests_returncode: int,
    typecheck_returncode: int,
    tests_output: str,
    typecheck_output: str,
) -> VerificationResult:
    tests_passed = tests_returncode == 0
    typecheck_passed = typecheck_returncode == 0
    return VerificationResult(
        tests_passed=tests_passed,
        typecheck_passed=typecheck_passed,
        tests_output=tests_output,
        typecheck_output=typecheck_output,
        passed=tests_passed and typecheck_passed,
    )


class VerifierUnavailable(RuntimeError):
    """Raised when the persistent SBX verifier cannot be prepared or reached."""


class HiddenVerifier:
    """Grade candidates in a persistent mountless SBX microVM.

    A unique VM-private directory and Docker volume are used for every case.
    The microVM stays warm across cases; candidate code still executes only in
    disposable Docker containers without the Docker socket or test-time network.
    """

    _protected_names = frozenset(
        {
            ".corepack.env",
            ".npmrc",
            ".pnpmfile.cjs",
            ".vuebench-corepack",
            ".yarnrc",
            ".yarnrc.yml",
            "jsconfig.json",
            "npm-shrinkwrap.json",
            "package-lock.json",
            "package.json",
            "pnpm-lock.yaml",
            "pnpm-workspace.yaml",
            "tsconfig.json",
            "vite.config.js",
            "vite.config.mjs",
            "vite.config.ts",
            "vitest.config.js",
            "vitest.config.mjs",
            "vitest.config.ts",
            "yarn.lock",
        }
    )
    _protected_directories = frozenset({".git", "node_modules", ".vuebench-hidden"})

    def __init__(
        self,
        *,
        sbx_executable: str = "sbx",
        sandbox_name: str = DEFAULT_SANDBOX_NAME,
        command_timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
        sandbox_cpus: int = DEFAULT_SANDBOX_CPUS,
        sandbox_memory: str = DEFAULT_SANDBOX_MEMORY,
    ) -> None:
        if command_timeout_seconds <= 0:
            raise ValueError("command_timeout_seconds must be positive")
        if sandbox_cpus <= 0:
            raise ValueError("sandbox_cpus must be positive")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]+", sandbox_name):
            raise ValueError("sandbox_name is not a valid Docker Sandbox name")
        self.sbx_executable = sbx_executable
        self.sandbox_name = sandbox_name
        self.command_timeout_seconds = command_timeout_seconds
        self.sandbox_cpus = sandbox_cpus
        self.sandbox_memory = sandbox_memory
        self._ready = False

    def invalidate(self) -> None:
        """Require the next verification phase to re-check the SBX runtime."""
        self._ready = False

    def preflight(self, *, cwd: Path | None = None) -> None:
        """Create the mountless verifier once and prove it can execute commands."""
        if self._ready:
            return
        command_cwd = (cwd or Path.cwd()).resolve()
        listed = self._safe_run(
            [self.sbx_executable, "ls", "--json"],
            cwd=command_cwd,
        )
        if listed.returncode != 0:
            raise VerifierUnavailable(self._failure_message("sandbox listing", listed))
        try:
            sandbox = self._sandbox_record(listed.stdout)
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise VerifierUnavailable(f"invalid `sbx ls --json` output: {error}") from error

        needs_lifecycle_action = sandbox is None or (
            str(sandbox.get("status", "")).casefold() != "running"
        )
        if needs_lifecycle_action:
            diagnosed = self._safe_run(
                [self.sbx_executable, "diagnose", "--json"],
                cwd=command_cwd,
            )
            diagnostic_error = self._diagnostic_error(diagnosed)
            if diagnostic_error is not None:
                raise VerifierUnavailable(diagnostic_error)

        if sandbox is None:
            created = self._create_sandbox(cwd=command_cwd)
            if created.returncode != 0:
                raise VerifierUnavailable(self._failure_message("sandbox creation", created))
        elif str(sandbox.get("status", "")).casefold() != "running":
            restarted = self._safe_run(
                [
                    self.sbx_executable,
                    "run",
                    "--detached",
                    "--name",
                    self.sandbox_name,
                ],
                cwd=command_cwd,
            )
            if restarted.returncode != 0:
                restart_output = _combined_output(restarted).casefold()
                if "container missing before start" not in restart_output:
                    raise VerifierUnavailable(self._failure_message("sandbox restart", restarted))
                removed = self._safe_run(
                    [self.sbx_executable, "rm", "--force", self.sandbox_name],
                    cwd=command_cwd,
                )
                if removed.returncode != 0:
                    raise VerifierUnavailable(
                        self._failure_message("stale sandbox removal", removed)
                    )
                created = self._create_sandbox(cwd=command_cwd)
                if created.returncode != 0:
                    raise VerifierUnavailable(self._failure_message("sandbox recreation", created))

        probe = self._safe_run(
            [self.sbx_executable, "exec", self.sandbox_name, "true"],
            cwd=command_cwd,
        )
        if probe.returncode != 0:
            raise VerifierUnavailable(self._failure_message("sandbox readiness probe", probe))
        self._ready = True

    def _create_sandbox(self, *, cwd: Path) -> subprocess.CompletedProcess[str]:
        return self._safe_run(
            [
                self.sbx_executable,
                "create",
                "--pull",
                "missing",
                "--cpus",
                str(self.sandbox_cpus),
                "--memory",
                self.sandbox_memory,
                "--quiet",
                "--name",
                self.sandbox_name,
                "shell",
            ],
            cwd=cwd,
        )

    def _diagnostic_error(self, result: subprocess.CompletedProcess[str]) -> str | None:
        try:
            payload = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            if result.returncode == 0:
                return "invalid `sbx diagnose --json` output"
            return self._failure_message("SBX diagnostics", result)
        checks = payload.get("checks")
        if not isinstance(checks, list):
            return "invalid `sbx diagnose --json` output: missing checks list"
        failures = [
            check for check in checks if isinstance(check, dict) and check.get("status") == "fail"
        ]
        if not failures and result.returncode == 0:
            return None
        details = "; ".join(
            f"{check.get('name', 'unknown check')}: {check.get('message', 'failed')}"
            for check in failures
        )
        if not details:
            details = _combined_output(result)
        return (
            f"SBX diagnostics failed: {details}; try `sbx daemon restart`, then "
            "`vuebench verifier init`"
        )

    def status(self, *, cwd: Path | None = None) -> dict[str, Any] | None:
        command_cwd = (cwd or Path.cwd()).resolve()
        listed = self._safe_run(
            [self.sbx_executable, "ls", "--json"],
            cwd=command_cwd,
        )
        if listed.returncode != 0:
            raise VerifierUnavailable(self._failure_message("sandbox listing", listed))
        payload = json.loads(listed.stdout)
        for sandbox in payload.get("sandboxes", []):
            if isinstance(sandbox, dict) and sandbox.get("name") == self.sandbox_name:
                return sandbox
        return None

    def remove(self, *, cwd: Path | None = None) -> bool:
        command_cwd = (cwd or Path.cwd()).resolve()
        if self.status(cwd=command_cwd) is None:
            self._ready = False
            return False
        removed = self._safe_run(
            [self.sbx_executable, "rm", "--force", self.sandbox_name],
            cwd=command_cwd,
        )
        if removed.returncode != 0:
            raise VerifierUnavailable(self._failure_message("sandbox removal", removed))
        self._ready = False
        return True

    def run(
        self,
        *,
        task_verifier: Path,
        workspace: Path,
        starter: Path | None = None,
        node: int = DEFAULT_NODE_VERSION,
        package_manager: str = "pnpm",
    ) -> VerificationResult:
        if package_manager != "pnpm":
            return self._infrastructure_failure(
                f"unsupported package manager for SBX verification: {package_manager}"
            )
        if node < DEFAULT_NODE_VERSION:
            return self._infrastructure_failure(
                f"unsupported Node.js runtime for SBX verification: {node} (requires >= 24)"
            )

        try:
            self.preflight(cwd=workspace)
        except VerifierUnavailable as error:
            return self._infrastructure_failure(str(error))

        pristine_starter = starter or task_verifier.parent / "starter"
        run_id = uuid.uuid4().hex
        run_root = RUNS_ROOT / run_id
        vm_workspace = run_root / "workspace"
        hidden_name = f".vuebench-hidden-{uuid.uuid4().hex}"
        hidden_vm_path = run_root / hidden_name
        tool_volume = f"vuebench-tools-{run_id}"
        dependency_volume = f"vuebench-deps-{run_id}"
        result: VerificationResult | None = None
        root_prepared = False
        created_volumes: list[str] = []

        with tempfile.TemporaryDirectory(prefix="vuebench-verify-") as temporary_directory:
            staging = Path(temporary_directory).resolve()
            try:
                self._copy_candidate(workspace, staging)
                self._restore_harness(pristine_starter, staging)

                prepared = self._safe_run(
                    [
                        self.sbx_executable,
                        "exec",
                        self.sandbox_name,
                        "mkdir",
                        "-p",
                        str(run_root),
                    ],
                    cwd=staging,
                )
                if prepared.returncode != 0:
                    result = self._command_failure("run directory setup", prepared)
                else:
                    root_prepared = True
                    copied = self._safe_run(
                        [
                            self.sbx_executable,
                            "cp",
                            str(staging),
                            f"{self.sandbox_name}:{vm_workspace}",
                        ],
                        cwd=staging,
                    )
                    if copied.returncode != 0:
                        result = self._command_failure("candidate transfer", copied)
                    else:
                        result = self._inject_verifier(
                            task_verifier=task_verifier,
                            hidden_vm_path=hidden_vm_path,
                            cwd=staging,
                        )

                if result is None:
                    volume = self._safe_run(
                        [
                            self.sbx_executable,
                            "exec",
                            self.sandbox_name,
                            "docker",
                            "volume",
                            "create",
                            tool_volume,
                        ],
                        cwd=staging,
                    )
                    if volume.returncode != 0:
                        result = self._command_failure("tool volume setup", volume)
                    else:
                        created_volumes.append(tool_volume)
                        dependencies = self._safe_run(
                            [
                                self.sbx_executable,
                                "exec",
                                self.sandbox_name,
                                "docker",
                                "volume",
                                "create",
                                dependency_volume,
                            ],
                            cwd=staging,
                        )
                        if dependencies.returncode != 0:
                            result = self._command_failure("dependency volume setup", dependencies)
                        else:
                            created_volumes.append(dependency_volume)

                if result is None:
                    install = self._safe_run(
                        self._setup_command(
                            vm_workspace=vm_workspace,
                            node=node,
                            tool_volume=tool_volume,
                            dependency_volume=dependency_volume,
                        ),
                        cwd=staging,
                    )
                    if install.returncode != 0:
                        result = self._command_failure("dependency installation", install)

                if result is None:
                    typecheck, typecheck_token = self._run_check(
                        cwd=staging,
                        vm_workspace=vm_workspace,
                        hidden_vm_path=hidden_vm_path,
                        hidden_name=hidden_name,
                        tool_volume=tool_volume,
                        dependency_volume=dependency_volume,
                        node=node,
                        command=(
                            f"{self._corepack_command()} {PINNED_PNPM} exec "
                            "vue-tsc --noEmit --project tsconfig.json"
                        ),
                    )
                    typecheck_status = self._parse_outer_status(typecheck, typecheck_token)
                    if typecheck_status is None:
                        result = self._status_failure("typecheck", typecheck)
                    else:
                        tests, tests_token = self._run_check(
                            cwd=staging,
                            vm_workspace=vm_workspace,
                            hidden_vm_path=hidden_vm_path,
                            hidden_name=hidden_name,
                            tool_volume=tool_volume,
                            dependency_volume=dependency_volume,
                            node=node,
                            command=(
                                f"{self._corepack_command()} {PINNED_PNPM} exec "
                                "vitest run --config vite.config.ts "
                                f"--passWithNoTests=false {hidden_name}"
                            ),
                        )
                        tests_status = self._parse_outer_status(tests, tests_token)
                        if tests_status is None:
                            result = self._status_failure("hidden tests", tests)
                        else:
                            result = parse_verification_result(
                                tests_returncode=tests_status,
                                typecheck_returncode=typecheck_status,
                                tests_output=_combined_output(tests),
                                typecheck_output=_combined_output(typecheck),
                            )
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                result = self._infrastructure_failure(
                    f"verification setup failed: {type(error).__name__}: {error}"
                )
            finally:
                cleanup_errors = self._cleanup_run(
                    cwd=staging,
                    run_root=run_root if root_prepared else None,
                    volumes=created_volumes,
                )
                if cleanup_errors:
                    cleanup_message = "; ".join(cleanup_errors)
                    if result is None:
                        result = self._infrastructure_failure(cleanup_message)
                    else:
                        prior = result.infrastructure_error or (
                            "checks passed" if result.passed else "checks failed"
                        )
                        result.infrastructure_error = (
                            f"prior verification result: {prior}; cleanup also failed: "
                            f"{cleanup_message}"
                        )
                        result.passed = False
                self.invalidate()

        return result or self._infrastructure_failure("verification produced no result")

    def _sandbox_record(self, output: str) -> dict[str, Any] | None:
        payload = json.loads(output)
        sandboxes = payload.get("sandboxes")
        if not isinstance(sandboxes, list):
            raise ValueError("missing sandboxes list")
        for sandbox in sandboxes:
            if isinstance(sandbox, dict) and sandbox.get("name") == self.sandbox_name:
                return sandbox
        return None

    def _inject_verifier(
        self,
        *,
        task_verifier: Path,
        hidden_vm_path: PurePosixPath,
        cwd: Path,
    ) -> VerificationResult | None:
        files = sorted(path for path in task_verifier.rglob("*") if path.is_file())
        for source in files:
            if source.is_symlink():
                return self._infrastructure_failure(
                    f"hidden verifier contains unsupported symlink: {source}"
                )
            relative = source.relative_to(task_verifier)
            target = hidden_vm_path / PurePosixPath(relative.as_posix())
            command = (
                f"mkdir -p {shlex.quote(str(target.parent))} && cat > {shlex.quote(str(target))}"
            )
            injected = self._safe_run(
                [self.sbx_executable, "exec", self.sandbox_name, "sh", "-lc", command],
                cwd=cwd,
                input_text=source.read_text(encoding="utf-8"),
            )
            if injected.returncode != 0:
                return self._command_failure("hidden verifier injection", injected)
        return None

    def _run_check(
        self,
        *,
        cwd: Path,
        vm_workspace: PurePosixPath,
        hidden_vm_path: PurePosixPath,
        hidden_name: str,
        tool_volume: str,
        dependency_volume: str,
        node: int,
        command: str,
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        docker_command = self._docker_check_command(
            vm_workspace=vm_workspace,
            hidden_vm_path=hidden_vm_path,
            hidden_name=hidden_name,
            tool_volume=tool_volume,
            dependency_volume=dependency_volume,
            node=node,
            command=command,
        )
        token = uuid.uuid4().hex
        wrapper = (
            f"{docker_command}; __vuebench_docker_exit=$?; "
            f"printf '\\n'; printf '{STATUS_PREFIX}{token}:%s\\n' "
            '"$__vuebench_docker_exit"; exit 0'
        )
        result = self._safe_run(
            [self.sbx_executable, "exec", self.sandbox_name, "sh", "-lc", wrapper],
            cwd=cwd,
        )
        return result, token

    def _setup_command(
        self,
        *,
        vm_workspace: PurePosixPath,
        node: int,
        tool_volume: str,
        dependency_volume: str,
    ) -> list[str]:
        script = (
            f"npm install --prefix /vuebench-tools --ignore-scripts {COREPACK_VERSION} && "
            f"COREPACK_HOME={COREPACK_HOME} {self._corepack_command()} install --global "
            f"{PINNED_PNPM} && "
            f"COREPACK_HOME={COREPACK_HOME} {self._corepack_command()} {PINNED_PNPM} "
            "install --frozen-lockfile --ignore-scripts --store-dir /vuebench-tools/store && "
            "mkdir -p /workspace/node_modules/.vite /workspace/node_modules/.vite-temp"
        )
        return self._docker_command(
            vm_workspace=vm_workspace,
            node=node,
            tool_volume=tool_volume,
            dependency_volume=dependency_volume,
            script=script,
        )

    def _docker_check_command(
        self,
        *,
        vm_workspace: PurePosixPath,
        hidden_vm_path: PurePosixPath,
        hidden_name: str,
        tool_volume: str,
        dependency_volume: str,
        node: int,
        command: str,
    ) -> str:
        args = self._docker_command(
            vm_workspace=vm_workspace,
            node=node,
            tool_volume=tool_volume,
            dependency_volume=dependency_volume,
            script=command,
            network_disabled=True,
            hidden_vm_path=hidden_vm_path,
            hidden_name=hidden_name,
            tool_read_only=True,
            dependency_read_only=True,
        )[4:]
        return "docker " + " ".join(shlex.quote(arg) for arg in args)

    def _docker_command(
        self,
        *,
        vm_workspace: PurePosixPath,
        node: int,
        tool_volume: str,
        dependency_volume: str,
        script: str,
        network_disabled: bool = False,
        hidden_vm_path: PurePosixPath | None = None,
        hidden_name: str | None = None,
        tool_read_only: bool = False,
        dependency_read_only: bool = False,
    ) -> list[str]:
        command = [self.sbx_executable, "exec", self.sandbox_name, "docker", "run", "--rm"]
        if network_disabled:
            command.extend(["--network", "none"])
        command.extend(
            [
                "-e",
                COREPACK_ENV,
                "-e",
                f"COREPACK_HOME={COREPACK_HOME}",
                "-v",
                f"{tool_volume}:/vuebench-tools{':ro' if tool_read_only else ''}",
                "-v",
                f"{vm_workspace}:/workspace",
                "-v",
                f"{dependency_volume}:/workspace/node_modules"
                f"{':ro' if dependency_read_only else ''}",
            ]
        )
        if dependency_read_only:
            command.extend(
                [
                    "--tmpfs",
                    "/workspace/node_modules/.vite",
                    "--tmpfs",
                    "/workspace/node_modules/.vite-temp",
                ]
            )
        if hidden_vm_path is not None and hidden_name is not None:
            command.extend(["-v", f"{hidden_vm_path}:/workspace/{hidden_name}:ro"])
        command.extend(
            [
                "-w",
                "/workspace",
                f"node:{node}-bookworm",
                "sh",
                "-lc",
                script,
            ]
        )
        return command

    def _cleanup_run(
        self,
        *,
        cwd: Path,
        run_root: PurePosixPath | None,
        volumes: list[str],
    ) -> list[str]:
        errors: list[str] = []
        if volumes:
            volume = self._safe_run(
                [
                    self.sbx_executable,
                    "exec",
                    self.sandbox_name,
                    "docker",
                    "volume",
                    "rm",
                    "--force",
                    *volumes,
                ],
                cwd=cwd,
            )
            if volume.returncode != 0:
                errors.append(self._failure_message("Docker volume cleanup", volume))
        if run_root is not None:
            directory = self._safe_run(
                [
                    self.sbx_executable,
                    "exec",
                    self.sandbox_name,
                    "sudo",
                    "rm",
                    "-rf",
                    "--",
                    str(run_root),
                ],
                cwd=cwd,
            )
            if directory.returncode != 0:
                errors.append(self._failure_message("run directory cleanup", directory))
        return errors

    @staticmethod
    def _corepack_command() -> str:
        return "/vuebench-tools/node_modules/.bin/corepack"

    @classmethod
    def _copy_candidate(cls, workspace: Path, destination: Path) -> None:
        cls._validate_candidate(workspace)
        ignore = shutil.ignore_patterns(*cls._protected_names, *cls._protected_directories)
        shutil.copytree(
            workspace,
            destination,
            dirs_exist_ok=True,
            ignore=ignore,
            symlinks=True,
        )

    @staticmethod
    def _validate_candidate(workspace: Path) -> None:
        for root, directories, files in os.walk(workspace, followlinks=False):
            for name in (*directories, *files):
                mode = os.lstat(Path(root) / name).st_mode
                special = (
                    stat.S_ISFIFO(mode)
                    or stat.S_ISSOCK(mode)
                    or stat.S_ISCHR(mode)
                    or stat.S_ISBLK(mode)
                )
                if special:
                    raise ValueError(
                        f"candidate contains unsupported filesystem entry: {Path(root) / name}"
                    )

    @classmethod
    def _restore_harness(cls, starter: Path, workspace: Path) -> None:
        for name in cls._protected_names:
            source = starter / name
            if not source.is_file():
                continue
            destination = workspace / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    def _safe_run(
        self,
        command: list[str],
        *,
        cwd: Path,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return self._run(command, cwd=cwd, input_text=input_text)
        except subprocess.TimeoutExpired as error:
            return subprocess.CompletedProcess(
                command,
                124,
                _text_output(error.stdout),
                f"command timed out after {self.command_timeout_seconds:g}s",
            )
        except OSError as error:
            return subprocess.CompletedProcess(command, 127, "", f"{type(error).__name__}: {error}")

    def _run(
        self,
        command: list[str],
        *,
        cwd: Path,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=cwd,
            text=True,
            input=input_text,
            capture_output=True,
            check=False,
            timeout=self.command_timeout_seconds,
        )

    @staticmethod
    def _parse_outer_status(result: subprocess.CompletedProcess[str], token: str) -> int | None:
        if result.returncode != 0:
            return None
        pattern = rf"{re.escape(STATUS_PREFIX)}{re.escape(token)}:(\d+)"
        for stream in (result.stdout, result.stderr):
            lines = stream.splitlines()
            if not lines:
                continue
            match = re.fullmatch(pattern, lines[-1])
            if match is None:
                continue
            status = int(match.group(1))
            if status in {125, 126, 127} or status >= 128:
                return None
            return status
        return None

    @classmethod
    def _status_failure(
        cls, phase: str, result: subprocess.CompletedProcess[str]
    ) -> VerificationResult:
        return cls._infrastructure_failure(
            f"{phase} execution failed: missing/invalid status marker or outer command "
            f"failure ({result.returncode}): {_combined_output(result)}"
        )

    @classmethod
    def _command_failure(
        cls, phase: str, result: subprocess.CompletedProcess[str]
    ) -> VerificationResult:
        return cls._infrastructure_failure(cls._failure_message(phase, result))

    @staticmethod
    def _failure_message(phase: str, result: subprocess.CompletedProcess[str]) -> str:
        return f"{phase} failed (exit {result.returncode}): {_combined_output(result)}"

    @staticmethod
    def _infrastructure_failure(reason: str) -> VerificationResult:
        return VerificationResult(
            tests_passed=False,
            typecheck_passed=False,
            tests_output=reason,
            typecheck_output=reason,
            passed=False,
            infrastructure_error=reason,
        )


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in (result.stdout, result.stderr) if part)


def _text_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value


__all__ = [
    "DEFAULT_SANDBOX_NAME",
    "HiddenVerifier",
    "VerifierUnavailable",
    "parse_verification_result",
]
