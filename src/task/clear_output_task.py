from __future__ import annotations

import shutil
from pathlib import Path

from common import cfg

from . import task_manager


def _resolve_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (Path.cwd() / path).resolve()


def _ensure_directory(directory: Path) -> Path:
    resolved = directory.resolve()
    if resolved.exists() and not resolved.is_dir():
        raise NotADirectoryError(f"expected directory path, got file: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _clear_directory(directory: Path) -> int:
    removed = 0
    for child in directory.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
        removed += 1
    return removed


@task_manager.manager.register
class ClearOutputTask:
    """Clear the output directory while keeping the directory itself."""

    TASK_ID = "clear_output"

    def execute(self, args, params):
        try:
            target_value = str(params.get("output_dir") or (Path(cfg.current_dir) / "output"))
            target_dir = _ensure_directory(_resolve_path(target_value))
            removed_count = _clear_directory(target_dir)
            print(f"clear_output done: removed={removed_count}, dir={target_dir}")
        except Exception as exc:
            print(f"clear_output_task error: {exc}")


@task_manager.manager.register
class ClearDirTaskCompat(ClearOutputTask):
    """Compatibility alias for legacy task id clear_dir."""

    TASK_ID = "clear_dir"
