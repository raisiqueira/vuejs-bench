from pathlib import Path
from typing import Any

from vuebench.agents.native import DEFAULT_TIMEOUT_SECONDS, NativeAgentRunner


class OpenCodeRunner(NativeAgentRunner):
    name = "opencode"

    def __init__(
        self,
        executable: str = "opencode",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        **kwargs: Any,
    ) -> None:
        super().__init__(timeout_seconds=timeout_seconds, **kwargs)
        self.executable = executable

    def _agent_command(
        self, *, cwd: Path, model: str | None, effort: str | None, prompt: str | None
    ) -> list[str]:
        if prompt is None:
            raise ValueError("OpenCode requires a prompt when building its run command")
        command = [
            self.executable,
            "run",
            "--pure",
            "--auto",
            "--dir",
            str(cwd),
            "--format",
            "default",
        ]
        if effort:
            command.extend(["--variant", effort])
        if model:
            command.extend(["--model", model])
        command.append(prompt)
        return command

    def prompt_input(self, prompt: str) -> None:
        return None


__all__ = ["OpenCodeRunner"]
