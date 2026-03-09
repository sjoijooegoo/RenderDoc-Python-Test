from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from common import cfg
from . import task_manager
from parse.material_shader_parser import parse_capture_material_shader


def _resolve_path(path_value: str, base_dir: Optional[Path] = None) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    if base_dir is not None:
        candidate = (base_dir / path).resolve()
        if candidate.exists():
            return candidate
    return (Path.cwd() / path).resolve()


def _to_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _find_latest_rdc(save_dir: Path) -> Optional[Path]:
    if not save_dir.exists():
        return None
    files = sorted(save_dir.glob("*.rdc"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


@task_manager.manager.register
class ParseRdcTask:
    """Parse one .rdc and output material/shader JSON report."""

    TASK_ID = "rdc_parse"

    def execute(self, args, params):
        try:
            save_dir = _resolve_path(params.get("save_dir", cfg.save_dir))
            rdc_arg = params.get("rdc") or params.get("input") or params.get("file")

            if rdc_arg:
                rdc_path = _resolve_path(rdc_arg, save_dir)
            else:
                rdc_path = _find_latest_rdc(save_dir)
                if rdc_path is None:
                    raise RuntimeError(f"no .rdc file found in {save_dir}")

            if not rdc_path.exists() or rdc_path.suffix.lower() != ".rdc":
                raise RuntimeError(f"invalid rdc file: {rdc_path}")

            output_path = _resolve_path(
                params.get("output") or params.get("out") or "output/rdc_material_shader.json"
            )
            include_source = _to_bool(params.get("include_source"), default=False)

            print(f"rdc_parse start: {rdc_path}")
            payload = parse_capture_material_shader(str(rdc_path), include_source=include_source)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            summary = payload.get("summary", {})
            print(f"report saved: {output_path}")
            print(
                "summary: "
                f"materials={summary.get('material_count', 0)}, "
                f"shaders={summary.get('shader_count', 0)}, "
                f"shader_lines_unique={summary.get('shader_total_lines_unique', 0)}, "
                f"shader_lines_by_usage={summary.get('shader_total_lines_by_usage', 0)}"
            )

        except Exception as exc:
            print(f"rdc_parse_task error: {exc}")


@task_manager.manager.register
class ParseRdcTaskCompat(ParseRdcTask):
    """Compatibility alias for legacy task id parse_rdc."""

    TASK_ID = "parse_rdc"
