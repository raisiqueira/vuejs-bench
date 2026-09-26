import os
import shutil
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
            "--agent",
            "build",
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

    def process_environment(self, *, scratch: Path) -> dict[str, str]:
        environment = super().process_environment(scratch=scratch)
        home = Path.home()
        data_source = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share")) / "opencode"
        config_source = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "opencode"
        data_dir = scratch / "xdg-data" / "opencode"
        config_dir = scratch / "xdg-config" / "opencode"
        data_dir.mkdir(parents=True, mode=0o700)
        config_dir.mkdir(parents=True, mode=0o700)
        for source, destination in (
            (data_source / "auth.json", data_dir / "auth.json"),
            (config_source / "opencode.json", config_dir / "opencode.json"),
            (config_source / "opencode.jsonc", config_dir / "opencode.jsonc"),
        ):
            if source.is_file():
                shutil.copyfile(source, destination)
                destination.chmod(0o600)
        environment.update(
            {
                "HOME": str(scratch),
                "TMP": str(scratch),
                "TEMP": str(scratch),
                "BUN_INSTALL_CACHE_DIR": str(scratch / "bun-cache"),
                "BUN_TMPDIR": str(scratch),
                "XDG_CACHE_HOME": str(scratch / "xdg-cache"),
                "XDG_CONFIG_HOME": str(scratch / "xdg-config"),
                "XDG_DATA_HOME": str(scratch / "xdg-data"),
                "XDG_STATE_HOME": str(scratch / "xdg-state"),
                "OPENCODE_DISABLE_AUTOUPDATE": "1",
                "OPENCODE_DISABLE_PRUNE": "1",
            }
        )
        environment.pop("OPENCODE_CONFIG", None)
        environment.pop("OPENCODE_CONFIG_DIR", None)
        return environment


__all__ = ["OpenCodeRunner"]
