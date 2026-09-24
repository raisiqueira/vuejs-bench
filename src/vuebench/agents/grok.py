import shutil
from pathlib import Path
from typing import Any

from vuebench.agents.native import DEFAULT_TIMEOUT_SECONDS, NativeAgentRunner


class GrokRunner(NativeAgentRunner):
    """Run Grok Build headlessly with isolated writable state."""

    name = "grok"

    def __init__(
        self,
        executable: str = "grok",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        *,
        auth_path: Path | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(timeout_seconds=timeout_seconds, **kwargs)
        self.executable = executable
        self.auth_path = auth_path or Path.home() / ".grok" / "auth.json"

    def _agent_command(
        self, *, cwd: Path, model: str | None, effort: str | None, prompt: str | None
    ) -> list[str]:
        if prompt is None:
            raise ValueError("Grok Build requires a prompt for a headless run")
        command = [
            self.executable,
            "--cwd",
            str(cwd),
            "--always-approve",
            "--no-alt-screen",
            "--no-plan",
            "--output-format",
            "plain",
        ]
        if effort:
            command.extend(["--reasoning-effort", effort])
        if model:
            command.extend(["--model", model])
        command.extend(["--single", prompt])
        return command

    def prompt_input(self, prompt: str) -> None:
        return None

    def process_environment(self, *, scratch: Path) -> dict[str, str]:
        environment = super().process_environment(scratch=scratch)
        scratch_value = str(scratch)
        grok_home = scratch / ".grok"
        grok_home.mkdir(mode=0o700, exist_ok=True)
        scratch_config = grok_home / "config.toml"
        scratch_config.write_text("")
        scratch_config.chmod(0o600)
        environment.pop("GROK_AUTH_PATH", None)
        environment.update(
            {
                "GROK_AGENT_DASHBOARD": "0",
                "GROK_CONFIG_PATH": str(scratch_config),
                "GROK_DISABLE_AUTOUPDATER": "1",
                "HOME": scratch_value,
                "TEMP": scratch_value,
                "TMP": scratch_value,
                "XDG_CACHE_HOME": str(scratch / "xdg-cache"),
                "XDG_CONFIG_HOME": str(scratch / "xdg-config"),
                "XDG_DATA_HOME": str(scratch / "xdg-data"),
                "XDG_STATE_HOME": str(scratch / "xdg-state"),
            }
        )
        if self.auth_path.is_file():
            scratch_auth = grok_home / "auth.json"
            shutil.copyfile(self.auth_path, scratch_auth)
            scratch_auth.chmod(0o600)
            environment["GROK_AUTH_PATH"] = str(scratch_auth)
        return environment


__all__ = ["GrokRunner"]
