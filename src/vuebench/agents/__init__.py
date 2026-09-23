from vuebench.agents.base import AgentRunner
from vuebench.agents.claude import ClaudeRunner
from vuebench.agents.codex import CodexRunner, CodexSandboxUnavailable
from vuebench.agents.native import DEFAULT_TIMEOUT_SECONDS, NativeAgentSandboxUnavailable
from vuebench.agents.opencode import OpenCodeRunner
from vuebench.agents.ori import OriRunner

AGENT_NAMES = ("codex", "claude", "opencode", "ori")


def create_agent_runner(name: str, *, timeout_seconds: float) -> AgentRunner:
    if name == "codex":
        return CodexRunner(timeout_seconds=timeout_seconds)
    if name == "claude":
        return ClaudeRunner(timeout_seconds=timeout_seconds)
    if name == "opencode":
        return OpenCodeRunner(timeout_seconds=timeout_seconds)
    if name == "ori":
        return OriRunner(timeout_seconds=timeout_seconds)
    raise ValueError(f"unsupported agent: {name}")


__all__ = [
    "AGENT_NAMES",
    "AgentRunner",
    "ClaudeRunner",
    "CodexRunner",
    "CodexSandboxUnavailable",
    "DEFAULT_TIMEOUT_SECONDS",
    "NativeAgentSandboxUnavailable",
    "OpenCodeRunner",
    "OriRunner",
    "create_agent_runner",
]
