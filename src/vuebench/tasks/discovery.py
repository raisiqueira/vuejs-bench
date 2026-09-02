from collections import Counter
from pathlib import Path

import yaml

from vuebench.models import BenchmarkTask, RuntimeConfig


def load_task(task_yaml: Path) -> BenchmarkTask:
    """Parse one task.yaml and its adjacent instruction.md."""
    task_path = task_yaml.parent.resolve()
    raw = yaml.safe_load(task_yaml.read_text(encoding="utf-8")) or {}
    instruction_path = task_path / "instruction.md"
    if not instruction_path.is_file():
        raise FileNotFoundError(f"Task instruction is missing: {instruction_path}")
    payload = dict(raw)
    payload["path"] = task_path
    payload["instruction"] = instruction_path.read_text(encoding="utf-8").strip()
    payload["runtime"] = RuntimeConfig.model_validate(raw.get("runtime", {}))
    task = BenchmarkTask.model_validate(payload)
    if not task.starter_path.is_dir():
        raise FileNotFoundError(f"Task starter directory is missing: {task.starter_path}")
    if not task.verifier_path.is_dir():
        raise FileNotFoundError(f"Task verifier directory is missing: {task.verifier_path}")
    return task


def discover_tasks(tasks_root: Path) -> list[BenchmarkTask]:
    """Discover and deterministically sort every task.yaml below ``tasks_root``."""
    if not tasks_root.is_dir():
        raise FileNotFoundError(f"Tasks directory is missing: {tasks_root}")
    tasks = [load_task(path) for path in sorted(tasks_root.rglob("task.yaml"))]
    id_counts = Counter(task.id for task in tasks)
    duplicates = sorted(task_id for task_id, count in id_counts.items() if count > 1)
    if duplicates:
        raise ValueError(f"Duplicate task id(s): {', '.join(duplicates)}")
    return tasks
