import shutil
import subprocess
import tempfile
from pathlib import Path

from vuebench.models import VerificationResult


def parse_verification_result(
    *,
    tests_returncode: int,
    typecheck_returncode: int,
    tests_output: str,
    typecheck_output: str,
) -> VerificationResult:
    tests_passed = tests_returncode == 0
    typecheck_passed = typecheck_returncode == 0
    return VerificationResult(
        tests_passed=tests_passed,
        typecheck_passed=typecheck_passed,
        tests_output=tests_output,
        typecheck_output=typecheck_output,
        passed=tests_passed and typecheck_passed,
    )


class HiddenVerifier:
    """Run hidden checks in a clean, verifier-controlled project copy.

    The agent workspace is a candidate source tree, not a trusted test
    environment.  Verification therefore copies it to a disposable directory,
    restores the project harness from the pristine starter, and installs a new
    dependency tree before injecting hidden specs.
    """

    # These files control test collection, typechecking, package resolution, or
    # package-manager behavior.  They must never come from the candidate tree.
    _protected_names = frozenset(
        {
            ".npmrc",
            ".pnpmfile.cjs",
            ".yarnrc",
            ".yarnrc.yml",
            "jsconfig.json",
            "npm-shrinkwrap.json",
            "package-lock.json",
            "package.json",
            "pnpm-lock.yaml",
            "pnpm-workspace.yaml",
            "tsconfig.json",
            "vite.config.js",
            "vite.config.mjs",
            "vite.config.ts",
            "vitest.config.js",
            "vitest.config.mjs",
            "vitest.config.ts",
            "yarn.lock",
        }
    )
    _protected_directories = frozenset({".git", "node_modules", ".vuebench-hidden"})

    def __init__(self, *, pnpm_executable: str = "pnpm") -> None:
        self.pnpm_executable = pnpm_executable

    def run(
        self,
        *,
        task_verifier: Path,
        workspace: Path,
        starter: Path | None = None,
    ) -> VerificationResult:
        """Verify candidate source without trusting candidate tooling.

        ``starter`` is optional for compatibility with the original seam; task
        layouts place it next to ``verifier`` so it can be derived safely.
        """
        pristine_starter = starter or task_verifier.parent / "starter"
        with tempfile.TemporaryDirectory(prefix="vuebench-verify-") as temporary_directory:
            verification_workspace = Path(temporary_directory)
            self._copy_candidate(workspace, verification_workspace)
            self._restore_harness(pristine_starter, verification_workspace)

            install = self._safe_run(
                [self.pnpm_executable, "install", "--frozen-lockfile", "--ignore-scripts"],
                cwd=verification_workspace,
            )
            if install.returncode != 0:
                output = _combined_output(install)
                return parse_verification_result(
                    tests_returncode=install.returncode,
                    typecheck_returncode=install.returncode,
                    tests_output=f"dependency installation failed\n{output}".strip(),
                    typecheck_output="dependency installation failed",
                )

            # This name is generated after the agent exits and is never present
            # in the starter or candidate workspace, so agent-created paths
            # cannot preempt hidden-test injection.
            hidden_directory = Path(
                tempfile.mkdtemp(prefix=".vuebench-hidden-", dir=verification_workspace)
            )
            try:
                shutil.copytree(task_verifier, hidden_directory, dirs_exist_ok=True)
                tests = self._safe_run(
                    [
                        self.pnpm_executable,
                        "exec",
                        "vitest",
                        "run",
                        "--config",
                        "vite.config.ts",
                        "--passWithNoTests=false",
                        hidden_directory.name,
                    ],
                    cwd=verification_workspace,
                )
                typecheck = self._safe_run(
                    [
                        self.pnpm_executable,
                        "exec",
                        "vue-tsc",
                        "--noEmit",
                        "--project",
                        "tsconfig.json",
                    ],
                    cwd=verification_workspace,
                )
                return parse_verification_result(
                    tests_returncode=tests.returncode,
                    typecheck_returncode=typecheck.returncode,
                    tests_output=_combined_output(tests),
                    typecheck_output=_combined_output(typecheck),
                )
            finally:
                shutil.rmtree(hidden_directory, ignore_errors=True)

    @classmethod
    def _copy_candidate(cls, workspace: Path, destination: Path) -> None:
        def ignore(_: str, names: list[str]) -> set[str]:
            return {
                name
                for name in names
                if name in cls._protected_names or name in cls._protected_directories
            }

        shutil.copytree(workspace, destination, dirs_exist_ok=True, ignore=ignore)

    @classmethod
    def _restore_harness(cls, starter: Path, workspace: Path) -> None:
        for name in cls._protected_names:
            source = starter / name
            if not source.is_file():
                continue
            destination = workspace / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    def _safe_run(self, command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        try:
            return self._run(command, cwd=cwd)
        except OSError as error:
            return subprocess.CompletedProcess(command, 127, "", f"{type(error).__name__}: {error}")

    @staticmethod
    def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in (result.stdout, result.stderr) if part)
