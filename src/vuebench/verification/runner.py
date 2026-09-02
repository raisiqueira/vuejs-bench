import os
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import uuid
from pathlib import Path

from vuebench.models import VerificationResult

COREPACK_ENV = "COREPACK_ENV_FILE=0"
COREPACK_HOME = "/vuebench-tools/corepack"
COREPACK_VERSION = "corepack@0.33.0"
PINNED_PNPM = "pnpm@11.1.1"
DEFAULT_NODE_VERSION = 24
DEFAULT_COMMAND_TIMEOUT_SECONDS = 300.0
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


class HiddenVerifier:
    """Run hidden checks in a clone-backed, disposable Docker Sandbox VM."""

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
        command_timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    ) -> None:
        if command_timeout_seconds <= 0:
            raise ValueError("command_timeout_seconds must be positive")
        self.sbx_executable = sbx_executable
        self.command_timeout_seconds = command_timeout_seconds

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

        pristine_starter = starter or task_verifier.parent / "starter"
        sandbox_name = self._sandbox_name()
        tool_volume = self._volume_name()
        hidden_name = f".vuebench-hidden-{uuid.uuid4().hex}"
        result: VerificationResult | None = None
        with tempfile.TemporaryDirectory(prefix="vuebench-verify-") as temporary_directory:
            staging = Path(temporary_directory).resolve()
            hidden_vm_path = staging / hidden_name
            try:
                self._copy_candidate(workspace, staging)
                self._restore_harness(pristine_starter, staging)
                self._initialize_git(staging)

                create = self._safe_run(
                    [
                        self.sbx_executable,
                        "create",
                        "--clone",
                        "--quiet",
                        "--name",
                        sandbox_name,
                        "shell",
                        str(staging),
                    ],
                    cwd=staging,
                )
                if create.returncode != 0:
                    result = self._command_failure("sandbox creation", create)
                else:
                    result = self._inject_verifier(
                        task_verifier=task_verifier,
                        sandbox_name=sandbox_name,
                        hidden_vm_path=hidden_vm_path,
                        cwd=staging,
                    )
                    if result is None:
                        volume = self._safe_run(
                            [
                                self.sbx_executable,
                                "exec",
                                sandbox_name,
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
                            install = self._safe_run(
                                self._setup_command(
                                    sandbox_name=sandbox_name,
                                    staging=staging,
                                    node=node,
                                    tool_volume=tool_volume,
                                ),
                                cwd=staging,
                            )
                            if install.returncode != 0:
                                result = self._command_failure(
                                    "dependency installation", install
                                )
                            else:
                                # Typecheck runs first so tests cannot mutate the
                                # source used by the later correctness check.
                                typecheck, typecheck_token = self._run_check(
                                    sandbox_name=sandbox_name,
                                    staging=staging,
                                    hidden_vm_path=hidden_vm_path,
                                    hidden_name=hidden_name,
                                    tool_volume=tool_volume,
                                    node=node,
                                    command=(
                                        f"{self._corepack_command()} {PINNED_PNPM} exec "
                                        "vue-tsc --noEmit --project tsconfig.json"
                                    ),
                                )
                                typecheck_status = self._parse_outer_status(
                                    typecheck, typecheck_token
                                )
                                if typecheck_status is None:
                                    result = self._status_failure("typecheck", typecheck)
                                else:
                                    tests, tests_token = self._run_check(
                                        sandbox_name=sandbox_name,
                                        staging=staging,
                                        hidden_vm_path=hidden_vm_path,
                                        hidden_name=hidden_name,
                                        tool_volume=tool_volume,
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
                cleanup = self._safe_run(
                    [self.sbx_executable, "rm", "--force", sandbox_name],
                    cwd=staging,
                )
                if cleanup.returncode != 0:
                    cleanup_error = self._command_failure("sandbox cleanup", cleanup)
                    if result is None:
                        result = cleanup_error
                    else:
                        result.infrastructure_error = (
                            f"{cleanup_error.infrastructure_error}; "
                            f"prior verification result: {result.infrastructure_error or 'none'}"
                        )
                        result.passed = False

        return result or self._infrastructure_failure("verification produced no result")

    def _inject_verifier(
        self,
        *,
        task_verifier: Path,
        sandbox_name: str,
        hidden_vm_path: Path,
        cwd: Path,
    ) -> VerificationResult | None:
        files = sorted(path for path in task_verifier.rglob("*") if path.is_file())
        for source in files:
            if source.is_symlink():
                return self._infrastructure_failure(
                    f"hidden verifier contains unsupported symlink: {source}"
                )
            relative = source.relative_to(task_verifier)
            target = hidden_vm_path / relative
            command = (
                f"mkdir -p {shlex.quote(str(target.parent))} && "
                f"cat > {shlex.quote(str(target))}"
            )
            injected = self._safe_run(
                [self.sbx_executable, "exec", sandbox_name, "sh", "-lc", command],
                cwd=cwd,
                input_text=source.read_text(encoding="utf-8"),
            )
            if injected.returncode != 0:
                return self._command_failure("hidden verifier injection", injected)
        return None

    def _run_check(
        self,
        *,
        sandbox_name: str,
        staging: Path,
        hidden_vm_path: Path,
        hidden_name: str,
        tool_volume: str,
        node: int,
        command: str,
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        docker_command = self._docker_check_command(
            staging=staging,
            hidden_vm_path=hidden_vm_path,
            hidden_name=hidden_name,
            tool_volume=tool_volume,
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
            [self.sbx_executable, "exec", sandbox_name, "sh", "-lc", wrapper],
            cwd=staging,
        )
        return result, token

    def _setup_command(
        self, *, sandbox_name: str, staging: Path, node: int, tool_volume: str
    ) -> list[str]:
        script = (
            f"npm install --prefix /vuebench-tools --ignore-scripts {COREPACK_VERSION} && "
            f"COREPACK_HOME={COREPACK_HOME} {self._corepack_command()} install --global "
            f"{PINNED_PNPM} && "
            f"COREPACK_HOME={COREPACK_HOME} {self._corepack_command()} {PINNED_PNPM} "
            "install --frozen-lockfile --ignore-scripts"
        )
        return self._docker_command(
            sandbox_name=sandbox_name,
            staging=staging,
            node=node,
            tool_volume=tool_volume,
            script=script,
        )

    def _docker_check_command(
        self,
        *,
        staging: Path,
        hidden_vm_path: Path,
        hidden_name: str,
        tool_volume: str,
        node: int,
        command: str,
    ) -> str:
        args = self._docker_command(
            sandbox_name="",
            staging=staging,
            node=node,
            tool_volume=tool_volume,
            script=command,
            network_disabled=True,
            hidden_vm_path=hidden_vm_path,
            hidden_name=hidden_name,
            tool_read_only=True,
        )[4:]
        return "docker " + " ".join(shlex.quote(arg) for arg in args)

    def _docker_command(
        self,
        *,
        sandbox_name: str,
        staging: Path,
        node: int,
        tool_volume: str,
        script: str,
        network_disabled: bool = False,
        hidden_vm_path: Path | None = None,
        hidden_name: str | None = None,
        tool_read_only: bool = False,
    ) -> list[str]:
        command = [self.sbx_executable, "exec", sandbox_name, "docker", "run", "--rm"]
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
                f"{staging}:/workspace",
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

    @staticmethod
    def _corepack_command() -> str:
        return "/vuebench-tools/node_modules/.bin/corepack"

    @staticmethod
    def _sandbox_name() -> str:
        return f"vuebench-verify-{uuid.uuid4().hex}"

    @staticmethod
    def _volume_name() -> str:
        return f"vuebench-tools-{uuid.uuid4().hex}"

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
                        "candidate contains unsupported filesystem entry: "
                        f"{Path(root) / name}"
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

    @staticmethod
    def _initialize_git(staging: Path) -> None:
        commands = [
            ["git", "init", "--quiet"],
            ["git", "add", "--all"],
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "user.email=vuebench@example.invalid",
                "-c",
                "user.name=VueBench",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--quiet",
                "--allow-empty",
                "-m",
                "verification-staging",
            ],
        ]
        for command in commands:
            subprocess.run(command, cwd=staging, check=True, capture_output=True, text=True)

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
    def _parse_outer_status(
        result: subprocess.CompletedProcess[str], token: str
    ) -> int | None:
        if result.returncode != 0:
            return None
        pattern = rf"{re.escape(STATUS_PREFIX)}{re.escape(token)}:(\d+)"
        # The trusted wrapper writes its marker to stdout after Docker exits.
        # Keep stderr as a fallback for fake executors and unusual shell setups.
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
        return cls._infrastructure_failure(
            f"{phase} failed (exit {result.returncode}): {_combined_output(result)}"
        )

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
