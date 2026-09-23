from pathlib import Path
from typing import Any

from vuebench.agents.native import DEFAULT_TIMEOUT_SECONDS, NativeAgentRunner


class OriRunner(NativeAgentRunner):
    """Run Ori Code headlessly with an OpenRouter model."""

    name = "ori"

    def __init__(
        self,
        executable: str = "ori",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        **kwargs: Any,
    ) -> None:
        super().__init__(timeout_seconds=timeout_seconds, **kwargs)
        self.executable = executable

    def _agent_command(self, *, cwd: Path, model: str | None, prompt: str | None) -> list[str]:
        if prompt is None:
            raise ValueError("Ori Code requires a prompt for a headless run")
        command = [
            self.executable,
            "code",
            "--approvals",
            "self-drive",
            "--output",
            "text",
        ]
        if model:
            command.extend(["--model", model])
        command.extend(["--prompt", prompt])
        return command

    def prompt_input(self, prompt: str) -> None:
        return None

    def process_environment(self, *, scratch: Path) -> dict[str, str]:
        environment = super().process_environment(scratch=scratch)
        scratch_value = str(scratch)
        environment.update(
            {
                "BUN_INSTALL_CACHE_DIR": str(scratch / "bun-cache"),
                "BUN_TMPDIR": scratch_value,
                "HOME": scratch_value,
                "TEMP": scratch_value,
                "TMP": scratch_value,
                "XDG_CACHE_HOME": str(scratch / "xdg-cache"),
                "XDG_CONFIG_HOME": str(scratch / "xdg-config"),
                "XDG_DATA_HOME": str(scratch / "xdg-data"),
                "XDG_STATE_HOME": str(scratch / "xdg-state"),
            }
        )
        return environment


__all__ = ["OriRunner"]
