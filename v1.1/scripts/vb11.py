"""Build VueBench v1.1 Harbor tasks from real GitHub fixes.

Usage:
    python3 v1.1/scripts/vb11.py build [TASK_ID ...]
    python3 v1.1/scripts/vb11.py discover [TASK_ID ...]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = ROOT / "sources"
TASKS_DIR = ROOT / "tasks"
CACHE_DIR = ROOT / ".cache" / "repos"
GRADER = Path(__file__).resolve().parent / "grade.mjs"

REPO_ROOT_IN_ENV = "/testbed"
BASE_IMAGE = (
    "node:24.22.1-bookworm"
    "@sha256:6449e19d8184d84062525b6a7524def03146c2cb04a7f08b076680d0e8e4240a"
)
TEST_FILE_PATTERN = re.compile(r"(\.(test|spec)\.[cm]?[jt]sx?$)|(/__tests__/)")

# Model provider endpoints the agent may reach. Add others with --allow-agent-host.
AGENT_ALLOWED_HOSTS = [
    "api.anthropic.com",
    "api.openai.com",
    "openrouter.ai",
    "opencode.ai",
    "models.dev",
]

DOCKERFILE = """\
FROM {base_image}

ENV CI=true \\
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0

RUN corepack enable \\
    && corepack prepare pnpm@{pnpm} --activate \\
    && git config --global user.name "VueBench" \\
    && git config --global user.email "vuebench@localhost" \\
    && git config --global init.defaultBranch main

WORKDIR {repo_root}

# Snapshot the base commit without any history, so the fix is not reachable.
RUN git init -q \\
    && git fetch -q --depth 1 https://github.com/{repo}.git {base_commit} \\
    && git checkout -q FETCH_HEAD \\
    && rm -rf .git \\
    && git init -q \\
    && git add -A \\
    && git commit -q -m "Base snapshot"

RUN pnpm install --frozen-lockfile --ignore-scripts
"""

SOLVE_SH = """\
#!/bin/bash
set -euo pipefail

cd {repo_root}
git apply --whitespace=nowarn /solution/fix.patch
"""

TEST_SH = """\
#!/bin/bash
set -uo pipefail

LOG_DIR=/logs/verifier
mkdir -p "$LOG_DIR"
echo 0 > "$LOG_DIR/reward.txt"

# Restore the official tests and the trusted test configuration over the candidate.
cp -a /tests/files/. {repo_root}/

cd {workdir}
./node_modules/.bin/vitest run --config {config} {vitest_args}\\
  --reporter=default --reporter=json --outputFile.json="$LOG_DIR/vitest.json" \\
  {test_files} 2>&1 | tee "$LOG_DIR/vitest.log"

node /tests/grade.mjs /tests/config.json "$LOG_DIR/vitest.json" "$LOG_DIR"
"""

TASK_TOML = """\
schema_version = "1.4"

[task]
name = "vuebench/{id}"
version = "1.1.0-poc"
description = {title}
keywords = ["vue", {repo_name}, {category}]

[metadata]
difficulty = {difficulty}
category = {category}
source_repo = {repo}
issue_url = {issue_url}
pr_url = {pr_url}
base_commit = {base_commit}
fix_commit = {fix_commit}
issue_created_at = {issue_created_at}
fix_merged_at = {fix_merged_at}

[environment]
# Public only for image build and agent install; each phase narrows it below.
network_mode = "public"
build_timeout_sec = 1800.0
cpus = 2
memory_mb = 4096

[agent]
timeout_sec = 900.0
network_mode = "allowlist"
allowed_hosts = {allowed_hosts}

[verifier]
timeout_sec = 600.0
network_mode = "no-network"
"""


@dataclass(frozen=True)
class Source:
    directory: Path
    data: dict

    @property
    def id(self) -> str:
        return str(self.data["task"]["id"])

    @property
    def repo(self) -> str:
        return str(self.data["source"]["repo"])

    @property
    def base(self) -> str:
        return str(self.data["source"]["base_commit"])

    @property
    def fix(self) -> str:
        return str(self.data["source"]["fix_commit"])

    @property
    def tests(self) -> dict:
        return dict(self.data["tests"])

    @property
    def discovered_path(self) -> Path:
        return self.directory / "tests.json"

    @property
    def task_dir(self) -> Path:
        return TASKS_DIR / self.id


def load_sources(ids: list[str]) -> list[Source]:
    sources = [
        Source(directory=path.parent, data=tomllib.loads(path.read_text()))
        for path in sorted(SOURCES_DIR.glob("*/source.toml"))
    ]
    if ids:
        known = {source.id for source in sources}
        if unknown := sorted(set(ids) - known):
            sys.exit(f"Unknown task ids: {', '.join(unknown)}")
        sources = [source for source in sources if source.id in ids]
    return sources


def git(repo_dir: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_dir), *args], check=True, capture_output=True, text=True
    ).stdout


def git_bytes(repo_dir: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo_dir), *args], check=True, capture_output=True
    ).stdout


def ensure_clone(source: Source) -> Path:
    repo_dir = CACHE_DIR / source.repo.replace("/", "__")
    if not repo_dir.exists():
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "git",
                "clone",
                "-q",
                "--filter=blob:none",
                "--no-checkout",
                f"https://github.com/{source.repo}.git",
                str(repo_dir),
            ],
            check=True,
        )
    for commit in (source.base, source.fix):
        if subprocess.run(
            ["git", "-C", str(repo_dir), "cat-file", "-e", f"{commit}^{{commit}}"],
            capture_output=True,
        ).returncode:
            git(repo_dir, "fetch", "-q", "origin", commit)
    return repo_dir


def split_changed_files(repo_dir: Path, source: Source) -> tuple[list[str], list[str]]:
    parents = git(repo_dir, "rev-list", "--parents", "-n", "1", source.fix).split()[1:]
    if parents != [source.base]:
        sys.exit(f"{source.id}: base_commit is not the only parent of fix_commit")
    changed = git(repo_dir, "diff", "--name-only", source.base, source.fix).split()
    test_files = [path for path in changed if TEST_FILE_PATTERN.search(path)]
    src_files = [path for path in changed if path not in test_files]
    if not test_files or not src_files:
        sys.exit(f"{source.id}: the fix must change both test and source files")
    return src_files, test_files


def expand_protected(repo_dir: Path, source: Source, src_files: list[str]) -> list[str]:
    files: list[str] = []
    for entry in source.tests["protected"]:
        matches = git(repo_dir, "ls-tree", "-r", "--name-only", source.base, "--", entry).split()
        if not matches:
            sys.exit(f"{source.id}: protected path {entry} does not exist at base")
        files.extend(matches)
    if overlap := sorted(set(files) & set(src_files)):
        sys.exit(f"{source.id}: protected paths overlap the fix: {', '.join(overlap)}")
    return files


def toml_str(value: object) -> str:
    return json.dumps(str(value))


def write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def build(source: Source) -> None:
    repo_dir = ensure_clone(source)
    src_files, test_files = split_changed_files(repo_dir, source)
    protected_files = expand_protected(repo_dir, source, src_files)
    tests = source.tests
    workdir = Path(REPO_ROOT_IN_ENV) / tests["workdir"]

    task_dir = source.task_dir
    if task_dir.exists():
        shutil.rmtree(task_dir)
    (task_dir / "environment").mkdir(parents=True)
    (task_dir / "solution").mkdir()
    files_dir = task_dir / "tests" / "files"
    files_dir.mkdir(parents=True)

    meta = source.data["source"]
    task = source.data["task"]
    issue_url = f"https://github.com/{source.repo}/issues/{meta['issue']}"
    pr_url = f"https://github.com/{source.repo}/pull/{meta['pr']}"
    (task_dir / "task.toml").write_text(
        TASK_TOML.format(
            id=source.id,
            title=toml_str(task["title"]),
            repo_name=toml_str(source.repo.split("/")[1]),
            category=toml_str(task["category"]),
            difficulty=toml_str(task["difficulty"]),
            repo=toml_str(source.repo),
            issue_url=toml_str(issue_url),
            pr_url=toml_str(pr_url),
            base_commit=toml_str(source.base),
            fix_commit=toml_str(source.fix),
            issue_created_at=toml_str(meta["issue_created_at"]),
            fix_merged_at=toml_str(meta["fix_merged_at"]),
            allowed_hosts=json.dumps(AGENT_ALLOWED_HOSTS),
        )
    )
    shutil.copyfile(source.directory / "instruction.md", task_dir / "instruction.md")
    (task_dir / "environment" / "Dockerfile").write_text(
        DOCKERFILE.format(
            base_image=BASE_IMAGE,
            pnpm=source.data["runtime"]["pnpm"],
            repo_root=REPO_ROOT_IN_ENV,
            repo=source.repo,
            base_commit=source.base,
        )
    )

    (task_dir / "solution" / "fix.patch").write_bytes(
        git_bytes(repo_dir, "diff", "--binary", source.base, source.fix, "--", *src_files)
    )
    write_executable(
        task_dir / "solution" / "solve.sh", SOLVE_SH.format(repo_root=REPO_ROOT_IN_ENV)
    )

    for path, commit in [(p, source.base) for p in protected_files] + [
        (p, source.fix) for p in test_files
    ]:
        target = files_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(git_bytes(repo_dir, "show", f"{commit}:{path}"))

    vitest_args = "".join(f"{arg} " for arg in tests["vitest_args"])
    relative_tests = " ".join(
        str(Path(REPO_ROOT_IN_ENV, path).relative_to(workdir)) for path in test_files
    )
    write_executable(
        task_dir / "tests" / "test.sh",
        TEST_SH.format(
            repo_root=REPO_ROOT_IN_ENV,
            workdir=workdir,
            config=tests["config"],
            vitest_args=vitest_args,
            test_files=relative_tests,
        ),
    )
    shutil.copyfile(GRADER, task_dir / "tests" / "grade.mjs")

    discovered = (
        json.loads(source.discovered_path.read_text())
        if source.discovered_path.exists()
        else {"fail_to_pass": [], "pass_to_pass": []}
    )
    config = {
        "task_id": source.id,
        "repo_root": REPO_ROOT_IN_ENV,
        "test_files": test_files,
        "fail_to_pass": discovered["fail_to_pass"],
        "pass_to_pass": discovered["pass_to_pass"],
    }
    (task_dir / "tests" / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    print(
        f"{source.id}: built ({len(src_files)} source files, {len(test_files)} test files, "
        f"{len(config['fail_to_pass'])} FAIL_TO_PASS, "
        f"{len(config['pass_to_pass'])} PASS_TO_PASS)"
    )


def run_tests_in_container(image: str, task_dir: Path, *, with_fix: bool) -> dict[str, bool]:
    with tempfile.TemporaryDirectory(prefix="vb11-") as logs:
        steps = ["bash /solution/solve.sh"] if with_fix else []
        steps.append("bash /tests/test.sh > /logs/verifier/test-output.txt 2>&1")
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "-v",
                f"{task_dir / 'tests'}:/tests:ro",
                "-v",
                f"{task_dir / 'solution'}:/solution:ro",
                "-v",
                f"{logs}:/logs/verifier",
                image,
                "bash",
                "-c",
                " && ".join(steps),
            ],
            check=True,
        )
        statuses_path = Path(logs) / "statuses.json"
        if not statuses_path.exists():
            output = (Path(logs) / "test-output.txt").read_text()
            sys.exit(f"{task_dir.name}: no test results\n{output[-4000:]}")
        statuses: dict[str, bool] = json.loads(statuses_path.read_text())
        return statuses


def discover(source: Source) -> None:
    if source.discovered_path.exists():
        source.discovered_path.unlink()
    build(source)
    image = f"vuebench-v1.1/{source.id}:discover"
    subprocess.run(
        ["docker", "build", "-q", "-t", image, str(source.task_dir / "environment")],
        check=True,
    )
    at_base = run_tests_in_container(image, source.task_dir, with_fix=False)
    with_fix = run_tests_in_container(image, source.task_dir, with_fix=True)

    fail_to_pass = sorted(i for i, ok in with_fix.items() if ok and not at_base.get(i, False))
    pass_to_pass = sorted(i for i, ok in with_fix.items() if ok and at_base.get(i, False))
    broken = sorted(i for i, ok in with_fix.items() if not ok)
    if not fail_to_pass:
        sys.exit(f"{source.id}: no FAIL_TO_PASS tests found")
    source.discovered_path.write_text(
        json.dumps(
            {"fail_to_pass": fail_to_pass, "pass_to_pass": pass_to_pass, "excluded": broken},
            indent=2,
        )
        + "\n"
    )
    for test_id in broken:
        print(f"{source.id}: excluded (does not pass with the fix): {test_id}")
    build(source)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["build", "discover"])
    parser.add_argument("task_ids", nargs="*")
    args = parser.parse_args()
    for source in load_sources(args.task_ids):
        build(source) if args.command == "build" else discover(source)


if __name__ == "__main__":
    main()
