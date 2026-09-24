import asyncio
import os
import shutil
import signal
import sys
import tempfile
import time
from abc import ABC, abstractmethod
from pathlib import Path

from vuebench.models import AgentResult

DEFAULT_TIMEOUT_SECONDS = 15 * 60
DEFAULT_DRAIN_TIMEOUT_SECONDS = 5.0
SANDBOX_EXECUTABLE = "/usr/bin/sandbox-exec"


class NativeAgentSandboxUnavailable(RuntimeError):
    """Raised when the macOS guard needed for a safe trial is unavailable."""


class NativeAgentRunner(ABC):
    """Common process, diff, and Seatbelt isolation for host-native agents."""

    name: str

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        sandbox_executable: str = SANDBOX_EXECUTABLE,
        drain_timeout_seconds: float = DEFAULT_DRAIN_TIMEOUT_SECONDS,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if drain_timeout_seconds <= 0:
            raise ValueError("drain_timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        self.sandbox_executable = sandbox_executable
        self.drain_timeout_seconds = drain_timeout_seconds

    def command(
        self,
        *,
        cwd: Path,
        source_repo_root: Path,
        model: str | None = None,
        effort: str | None = None,
        prompt: str | None = None,
        scratch: Path | None = None,
    ) -> list[str]:
        """Return the Seatbelt-wrapped, non-interactive agent argv."""
        self._require_sandbox()
        profile = self.sandbox_profile(
            source_repo_root=source_repo_root,
            workspace=cwd,
            scratch=scratch or cwd,
        )
        return [
            self.sandbox_executable,
            "-p",
            profile,
            "--",
            *self._agent_command(cwd=cwd, model=model, effort=effort, prompt=prompt),
        ]

    @abstractmethod
    def _agent_command(
        self, *, cwd: Path, model: str | None, effort: str | None, prompt: str | None
    ) -> list[str]:
        """Build the CLI-specific command inside the Seatbelt boundary."""

    def prompt_input(self, prompt: str) -> bytes | None:
        return prompt.encode()

    def process_environment(self, *, scratch: Path) -> dict[str, str]:
        environment = os.environ.copy()
        environment["TMPDIR"] = str(scratch)
        return environment

    @staticmethod
    def sandbox_profile(*, source_repo_root: Path, workspace: Path, scratch: Path) -> str:
        """Deny source reads and writes outside the trial workspace and runner scratch."""
        source = NativeAgentRunner._safe_profile_path(source_repo_root, "source repository")
        trial = NativeAgentRunner._safe_profile_path(workspace, "trial workspace")
        temporary = NativeAgentRunner._safe_profile_path(scratch, "agent scratch")
        return " ".join(
            [
                "(version 1)",
                "(allow default)",
                f'(deny file-read* (subpath "{source}"))',
                "(deny file-write* (require-all "
                f'(require-not (subpath "{trial}")) '
                f'(require-not (subpath "{temporary}")) '
                '(require-not (literal "/dev/null"))))',
            ]
        )

    @staticmethod
    def _safe_profile_path(path: Path, label: str) -> str:
        resolved = path.expanduser().resolve()
        if not resolved.is_dir():
            raise NativeAgentSandboxUnavailable(
                f"native agent isolation requires an existing {label} directory: {resolved}"
            )
        value = str(resolved)
        if any(character in value for character in "\r\n"):
            raise NativeAgentSandboxUnavailable(f"{label} path contains a newline")
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _require_sandbox(self) -> None:
        if sys.platform != "darwin":
            raise NativeAgentSandboxUnavailable(
                "VueBench native-agent trials require macOS /usr/bin/sandbox-exec; "
                "refusing to run unisolated"
            )
        executable = Path(self.sandbox_executable)
        if not executable.is_absolute():
            resolved = shutil.which(self.sandbox_executable)
            if resolved is None:
                raise NativeAgentSandboxUnavailable(
                    f"macOS Seatbelt executable not found: {self.sandbox_executable}"
                )
            executable = Path(resolved)
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise NativeAgentSandboxUnavailable(
                f"macOS Seatbelt executable is unavailable or not executable: {executable}"
            )

    async def run(
        self,
        *,
        cwd: Path,
        source_repo_root: Path,
        prompt: str,
        model: str | None = None,
        effort: str | None = None,
    ) -> AgentResult:
        started = time.monotonic()
        baseline = await self._git_revision(cwd)
        with tempfile.TemporaryDirectory(prefix="vuebench-agent-") as scratch_value:
            scratch = Path(scratch_value).resolve()
            command = self.command(
                cwd=cwd,
                source_repo_root=source_repo_root,
                model=model,
                effort=effort,
                prompt=prompt,
                scratch=scratch,
            )
            environment = self.process_environment(scratch=scratch)
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=cwd,
                env=environment,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            communication = asyncio.create_task(process.communicate(self.prompt_input(prompt)))
            timed_out = False
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    asyncio.shield(communication), timeout=self.timeout_seconds
                )
            except TimeoutError:
                timed_out = True
                await self._terminate_process_group(process, communication)
                try:
                    stdout_bytes, stderr_bytes = communication.result()
                except (asyncio.InvalidStateError, asyncio.CancelledError):
                    stdout_bytes, stderr_bytes = b"", b""
            else:
                self._terminate_remaining_descendants(process.pid)

            if timed_out:
                stderr_bytes += f"\n{self.name} process timed out.".encode()

        diff_bytes, diff_stderr = await self._capture_diff(cwd, baseline)
        if diff_stderr:
            stderr_bytes += b"\n" + diff_stderr
        return AgentResult(
            exit_code=process.returncode if process.returncode is not None else 1,
            stdout=stdout_bytes.decode(errors="replace"),
            stderr=stderr_bytes.decode(errors="replace"),
            diff=diff_bytes.decode(errors="replace"),
            duration_seconds=time.monotonic() - started,
        )

    async def _git_revision(self, cwd: Path) -> str:
        process = await asyncio.create_subprocess_exec(
            "git",
            "rev-parse",
            "HEAD",
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            details = stderr.decode(errors="replace").strip()
            raise RuntimeError(f"unable to capture starter commit: {details}")
        return stdout.decode(errors="replace").strip()

    async def _capture_diff(self, cwd: Path, baseline: str) -> tuple[bytes, bytes]:
        intent_process = await asyncio.create_subprocess_exec(
            "git",
            "add",
            "--intent-to-add",
            ".",
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, intent_stderr = await intent_process.communicate()
        diff_process = await asyncio.create_subprocess_exec(
            "git",
            "diff",
            "--no-ext-diff",
            baseline,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        diff_bytes, diff_stderr = await diff_process.communicate()
        if intent_stderr:
            diff_stderr = intent_stderr + b"\n" + diff_stderr
        return diff_bytes, diff_stderr

    @staticmethod
    def _terminate_remaining_descendants(process_group_id: int) -> None:
        """Stop background children an agent left behind after its main process exited."""
        try:
            os.killpg(process_group_id, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    async def _terminate_process_group(
        self,
        process: asyncio.subprocess.Process,
        communication: asyncio.Task[tuple[bytes, bytes]],
    ) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            if process.returncode is None:
                process.kill()
        try:
            await asyncio.wait_for(
                asyncio.shield(communication), timeout=self.drain_timeout_seconds
            )
            return
        except TimeoutError:
            communication.cancel()
            try:
                await communication
            except (asyncio.CancelledError, asyncio.InvalidStateError):
                pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            if process.returncode is None:
                process.kill()
        try:
            await asyncio.wait_for(process.wait(), timeout=self.drain_timeout_seconds)
        except TimeoutError:
            pass


__all__ = [
    "DEFAULT_DRAIN_TIMEOUT_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS",
    "NativeAgentRunner",
    "NativeAgentSandboxUnavailable",
    "SANDBOX_EXECUTABLE",
]
