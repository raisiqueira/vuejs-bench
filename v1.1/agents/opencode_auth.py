"""OpenCode agent that reuses the host OpenCode login instead of API key env vars.

Usage:
    PYTHONPATH=v1.1/agents harbor run -a opencode_auth:OpenCodeAuth -m opencode-go/<model> ...

Only the credential of the model's provider is copied from the host auth.json.
It lives outside /logs, so it never reaches the job results, and it is removed
after the run.
"""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path, PurePosixPath

from harbor.agents.installed.opencode import OpenCode
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

HOST_AUTH_PATH = Path(
    os.environ.get("OPENCODE_AUTH_JSON_PATH")
    or Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    / "opencode"
    / "auth.json"
)
REMOTE_SECRETS_DIR = PurePosixPath("/tmp/vuebench-opencode-secrets")


class OpenCodeAuth(OpenCode):
    @staticmethod
    def name() -> str:
        return "opencode-auth"

    def _provider_credentials(self) -> str:
        if not self.model_name or "/" not in self.model_name:
            raise ValueError("Model name must be in the format provider/model_name")
        provider = self.model_name.split("/", 1)[0]
        credentials = json.loads(HOST_AUTH_PATH.read_text())
        if provider not in credentials:
            raise ValueError(
                f"No OpenCode login for provider {provider!r} in {HOST_AUTH_PATH}. "
                f"Run `opencode auth login` first."
            )
        return json.dumps({provider: credentials[provider]})

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        remote_auth = REMOTE_SECRETS_DIR / "auth.json"
        # The base adapter points XDG_DATA_HOME here; OpenCode reads opencode/auth.json in it.
        auth_link = self.environment_logs_dir / "opencode" / "xdg-data" / "opencode" / "auth.json"
        quoted_dir = shlex.quote(REMOTE_SECRETS_DIR.as_posix())
        quoted_link = shlex.quote(auth_link.as_posix())

        await self.exec_as_root(environment, command=f"mkdir -p -m 700 {quoted_dir}")
        if environment.default_user is not None:
            owner = shlex.quote(str(environment.default_user))
            await self.exec_as_root(environment, command=f"chown {owner} {quoted_dir}")
        await self._upload_config_text(
            environment,
            content=self._provider_credentials(),
            remote_path=remote_auth.as_posix(),
            filename="auth.json",
        )
        await self.exec_as_agent(
            environment,
            command=(
                f"mkdir -p $(dirname {quoted_link}) && "
                f"ln -sf {shlex.quote(remote_auth.as_posix())} {quoted_link}"
            ),
        )
        try:
            await super().run(instruction, environment, context)
        finally:
            await self.exec_as_root(environment, command=f"rm -rf {quoted_dir} {quoted_link}")
