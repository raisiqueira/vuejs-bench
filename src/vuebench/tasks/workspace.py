import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from vuebench.models import BenchmarkTask


class TaskWorkspace:
    """A disposable, git-initialized copy of a task's starter project."""

    def __init__(self, path: Path, temporary_directory: tempfile.TemporaryDirectory[str]) -> None:
        self.path = path
        self._temporary_directory = temporary_directory

    def close(self) -> None:
        self._temporary_directory.cleanup()


class WorkspaceManager:
    def __init__(self, *, pnpm_executable: str = "pnpm") -> None:
        self.pnpm_executable = pnpm_executable

    @contextmanager
    def create(self, task: BenchmarkTask) -> Iterator[TaskWorkspace]:
        temporary_directory = tempfile.TemporaryDirectory(prefix=f"vuebench-{task.id}-")
        workspace = Path(temporary_directory.name)
        try:
            # Never carry a developer's dependency tree into a trial. Apart from
            # making copies expensive, pnpm's symlink layout can point back to a
            # different checkout; install a clean tree for each trial instead.
            shutil.copytree(
                task.starter_path,
                workspace,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("node_modules", ".vuebench-hidden"),
            )
            self._initialize_git(workspace)
            self.install_dependencies(workspace)
            yield TaskWorkspace(workspace, temporary_directory)
        finally:
            temporary_directory.cleanup()

    def _initialize_git(self, workspace: Path) -> None:
        self._run(["git", "init", "--quiet"], cwd=workspace)
        self._run(["git", "config", "user.email", "vuebench@example.invalid"], cwd=workspace)
        self._run(["git", "config", "user.name", "VueBench"], cwd=workspace)
        # Trial repositories are ephemeral and must not depend on a developer's
        # signing helper (which may block or fail in a non-interactive run).
        self._run(["git", "config", "commit.gpgsign", "false"], cwd=workspace)
        self._run(["git", "add", "--all"], cwd=workspace)
        self._run(["git", "commit", "--quiet", "-m", "starter"], cwd=workspace)

    def install_dependencies(self, workspace: Path) -> subprocess.CompletedProcess[str]:
        return self._run(
            # Some pnpm installations require an interactive build approval for
            # esbuild. The benchmark does not need arbitrary package lifecycle
            # scripts, and ignoring them keeps non-interactive runs reliable.
            [self.pnpm_executable, "install", "--frozen-lockfile", "--ignore-scripts"],
            cwd=workspace,
        )

    @staticmethod
    def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=True)
