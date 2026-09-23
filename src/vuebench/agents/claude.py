from pathlib import Path
from typing import Any

from vuebench.agents.native import DEFAULT_TIMEOUT_SECONDS, NativeAgentRunner


class ClaudeRunner(NativeAgentRunner):
    name = "claude"

    def __init__(
        self,
        executable: str = "claude",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        **kwargs: Any,
    ) -> None:
        super().__init__(timeout_seconds=timeout_seconds, **kwargs)
        self.executable = executable

    def _agent_command(self, *, cwd: Path, model: str | None, prompt: str | None) -> list[str]:
        command = [
            self.executable,
            "--print",
            "--safe-mode",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--dangerously-skip-permissions",
            "--permission-prompts",
            "none",
            "--output-format",
            "text",
        ]
        if model:
            command.extend(["--model", model])
        return command


__all__ = ["ClaudeRunner"]
