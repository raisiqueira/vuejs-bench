from pathlib import Path

from vuebench.agents.native import (
    DEFAULT_DRAIN_TIMEOUT_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    SANDBOX_EXECUTABLE,
    NativeAgentRunner,
    NativeAgentSandboxUnavailable,
)

CodexSandboxUnavailable = NativeAgentSandboxUnavailable


class CodexRunner(NativeAgentRunner):
    """Run Codex non-interactively behind the shared native-agent boundary."""

    name = "codex"

    def __init__(
        self,
        executable: str = "codex",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        *,
        sandbox_executable: str = SANDBOX_EXECUTABLE,
        drain_timeout_seconds: float = DEFAULT_DRAIN_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(
            timeout_seconds=timeout_seconds,
            sandbox_executable=sandbox_executable,
            drain_timeout_seconds=drain_timeout_seconds,
        )
        self.executable = executable

    def _agent_command(self, *, cwd: Path, model: str | None, prompt: str | None) -> list[str]:
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
    def sandbox_profile(
        source_repo_root: Path,
        workspace: Path | None = None,
        scratch: Path | None = None,
    ) -> str:
        # Keep the one-argument form for callers inspecting only the legacy
        # source-read rule. Real runs always include workspace write isolation.
        if workspace is None:
            source = NativeAgentRunner._safe_profile_path(source_repo_root, "source repository")
            return f'(version 1) (allow default) (deny file-read* (subpath "{source}"))'
        return NativeAgentRunner.sandbox_profile(
            source_repo_root=source_repo_root,
            workspace=workspace,
            scratch=scratch or workspace,
        )


__all__ = ["CodexRunner", "CodexSandboxUnavailable", "DEFAULT_TIMEOUT_SECONDS"]
