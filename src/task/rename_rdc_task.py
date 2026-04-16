'''
author: v_sycisong
LastEditors: v_sycisong
'''
import re
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from common import cfg

from . import task_manager


def _resolve_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (Path.cwd() / path).resolve()


def _extract_suffix_value(file_path: Path) -> Optional[int]:
    stem = file_path.stem
    frame_match = re.search(r"frame(\d+)$", stem, flags=re.IGNORECASE)
    if frame_match:
        return int(frame_match.group(1))

    tail_match = re.search(r"(\d+)$", stem)
    if tail_match:
        return int(tail_match.group(1))
    return None


def _is_legacy_temp_rdc(file_path: Path) -> bool:
    return file_path.suffix.lower() == ".rdc" and file_path.stem.startswith("__tmp_rdc_rename_")


def _collect_rdc_files(save_dir: Path) -> List[Tuple[Path, Tuple[int, int, str]]]:
    collected: List[Tuple[Path, Tuple[int, int, str]]] = []
    for rdc_file in save_dir.glob("*.rdc"):
        if _is_legacy_temp_rdc(rdc_file):
            # Recover old buggy temp artifacts by moving them after normal numbered files.
            stat = rdc_file.stat()
            collected.append((rdc_file, (2, int(stat.st_mtime_ns), rdc_file.name.lower())))
            continue

        suffix_value = _extract_suffix_value(rdc_file)
        if suffix_value is None:
            continue
        collected.append((rdc_file, (1, suffix_value, rdc_file.name.lower())))
    return collected


@task_manager.manager.register
class RenameRdcTask:
    """Rename .rdc files in save folder by numeric suffix order: 1.rdc, 2.rdc, ..."""

    TASK_ID = "rename_rdc"

    def execute(self, args, params):
        try:
            save_dir_raw = (
                params.get("output")
                or params.get("output_dir")
                or params.get("dir")
                or params.get("save_dir")
                or cfg.save_dir
            )
            save_dir = _resolve_path(save_dir_raw)
            if not save_dir.exists():
                raise RuntimeError(f"save dir not found: {save_dir}")
            if not save_dir.is_dir():
                raise RuntimeError(f"save dir is not a folder: {save_dir}")

            rdc_files = _collect_rdc_files(save_dir)
            if not rdc_files:
                raise RuntimeError(f"no valid .rdc files with numeric suffix found in: {save_dir}")

            rdc_files_sorted = sorted(rdc_files, key=lambda item: item[1])
            rename_plan: List[Tuple[Path, Path]] = []
            for index, (old_path, _sort_key) in enumerate(rdc_files_sorted, start=1):
                new_path = save_dir / f"{index}.rdc"
                rename_plan.append((old_path, new_path))

            temp_records: List[Tuple[Path, Path, Path]] = []
            for old_path, new_path in rename_plan:
                temp_name = f"__tmp_rdc_rename_{uuid.uuid4().hex}.tmp"
                temp_path = save_dir / temp_name
                old_path.rename(temp_path)
                temp_records.append((old_path, temp_path, new_path))

            for old_path, temp_path, new_path in temp_records:
                temp_path.rename(new_path)
                print(f"renamed: {old_path.name} -> {new_path.name}")

            print(f"rename_rdc done: {len(temp_records)} files in {save_dir}")
        except Exception as e:
            task_manager.emit_error_output(e)


@task_manager.manager.register
class RenameRdcTaskCompat(RenameRdcTask):
    """Compatibility alias for legacy task id rdc_rename."""

    TASK_ID = "rdc_rename"
