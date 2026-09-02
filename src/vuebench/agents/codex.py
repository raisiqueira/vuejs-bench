import asyncio
import os
import shutil
import signal
import sys
import time
from pathlib import Path

from vuebench.models import AgentResult

DEFAULT_TIMEOUT_SECONDS = 15 * 60
DEFAULT_DRAIN_TIMEOUT_SECONDS = 5.0
SANDBOX_EXECUTABLE = "/usr/bin/sandbox-exec"


class CodexSandboxUnavailable(RuntimeError):
    """Raised when the macOS guard needed for a safe trial is unavailable."""


class CodexRunner:
    """Run Codex behind a fail-closed macOS filesystem boundary.

    ``workspace-write`` controls writes made by Codex, but does not prevent it
    from reading the benchmark checkout. The outer Seatbelt profile denies
    reads of that checkout, including its Git objects and hidden verifiers.
    """

    def __init__(
        self,
        executable: str = "codex",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        *,
        sandbox_executable: str = SANDBOX_EXECUTABLE,
        drain_timeout_seconds: float = DEFAULT_DRAIN_TIMEOUT_SECONDS,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if drain_timeout_seconds <= 0:
            raise ValueError("drain_timeout_seconds must be positive")
        self.executable = executable
        self.timeout_seconds = timeout_seconds
        self.sandbox_executable = sandbox_executable
        self.drain_timeout_seconds = drain_timeout_seconds

    def command(
        self,
        *,
        cwd: Path,
        source_repo_root: Path,
        model: str | None = None,
    ) -> list[str]:
        """Return the Seatbelt-wrapped, non-interactive Codex argv."""
        self._require_sandbox()
        profile = self.sandbox_profile(source_repo_root)
        inner = self._codex_command(cwd=cwd, model=model)
        return [self.sandbox_executable, "-p", profile, "--", *inner]

    def _codex_command(self, *, cwd: Path, model: str | None = None) -> list[str]:
        # These flags prevent user config/rules from changing benchmark runs,
        # and make approval behavior deterministic and non-interactive.
        command = [
            self.executable,
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--cd",
            str(cwd),
            "--sandbox",
            "workspace-write",
            "-c",
            'approval_policy="never"',
            "--ephemeral",
            "--color",
            "never",
        ]
        if model:
            command.extend(["--model", model])
        return command

    @staticmethod
    def sandbox_profile(source_repo_root: Path) -> str:
        """Build a Seatbelt profile denying reads of the entire source repo."""
        root = source_repo_root.expanduser().resolve()
        if not root.is_dir():
            raise CodexSandboxUnavailable(
                f"Codex isolation requires an existing source repository directory: {root}"
            )
        value = str(root)
        if any(character in value for character in "\r\n"):
            raise CodexSandboxUnavailable("source repository path contains a newline")
        value = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'(version 1) (allow default) (deny file-read* (subpath "{value}"))'

    def _require_sandbox(self) -> None:
        if sys.platform != "darwin":
            raise CodexSandboxUnavailable(
                "VueBench Codex trials require macOS /usr/bin/sandbox-exec; "
                "refusing to run unisolated"
            )
        executable = Path(self.sandbox_executable)
        if not executable.is_absolute():
            resolved = shutil.which(self.sandbox_executable)
            if resolved is None:
                raise CodexSandboxUnavailable(
                    f"macOS Seatbelt executable not found: {self.sandbox_executable}"
                )
            executable = Path(resolved)
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise CodexSandboxUnavailable(
                f"macOS Seatbelt executable is unavailable or not executable: {executable}"
            )

    async def run(
        self,
        *,
        cwd: Path,
        source_repo_root: Path,
        prompt: str,
        model: str | None = None,
    ) -> AgentResult:
        started = time.monotonic()
        command = self.command(cwd=cwd, source_repo_root=source_repo_root, model=model)
        baseline = await self._git_revision(cwd)
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        communication = asyncio.create_task(process.communicate(prompt.encode()))
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

        if timed_out:
            stderr_bytes += b"\nCodex process timed out."

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
        # Intent-to-add exposes new, non-ignored files without staging their
        # contents. Diffing against the saved starter commit also includes
        # changes that Codex committed during the run.
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

    async def _terminate_process_group(
        self,
        process: asyncio.subprocess.Process,
        communication: asyncio.Task[tuple[bytes, bytes]],
    ) -> None:
        """Terminate Codex and descendants, then boundedly drain its pipes."""
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
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
    "CodexRunner",
    "CodexSandboxUnavailable",
    "DEFAULT_TIMEOUT_SECONDS",
]
