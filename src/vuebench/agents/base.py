from pathlib import Path
from typing import Protocol

from vuebench.models import AgentResult


class AgentRunner(Protocol):
    """Adapter boundary for coding-agent CLIs."""

    async def run(
        self,
        *,
        cwd: Path,
        source_repo_root: Path,
        prompt: str,
        model: str | None = None,
    ) -> AgentResult:
        """Run an agent in ``cwd`` and return its process and diff details."""
