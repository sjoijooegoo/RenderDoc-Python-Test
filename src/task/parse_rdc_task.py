from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from common import cfg
from parse.material_shader_parser import parse_capture_material_shader

from . import task_manager


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


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    safe = safe.strip("._")
    return safe or "capture"


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

            output_root = _resolve_path("output")
            capture_folder = output_root / _safe_name(rdc_path.stem)
            output_path = capture_folder / "rdc_entry.json"

            schema = "1"
            export_texture_assets = _to_bool(params.get("export_texture_assets"), default=True)
            export_shader_assets = _to_bool(params.get("export_shader_assets"), default=True)
            include_context_events = _to_bool(params.get("include_context_events"), default=False)
            emit_shaders = True
            source_output_dir = capture_folder / "rdc_shader" if export_shader_assets else None
            material_output_dir = capture_folder / "rdc_material"
            texture_output_dir = capture_folder / "rdc_texture"
            shader_output_dir = capture_folder / "rdc_shader"

            print(f"rdc_parse start: {rdc_path}")
            print(
                "rdc_parse options: "
                f"include_context_events={include_context_events}, emit_shaders=true, "
                f"export_texture_assets={export_texture_assets}, export_shader_assets={export_shader_assets}"
            )

            payload = parse_capture_material_shader(
                str(rdc_path),
                include_source=export_shader_assets,
                schema=schema,
                include_context_events=include_context_events,
                emit_shaders=emit_shaders,
                source_output_dir=str(source_output_dir) if source_output_dir is not None else None,
                material_output_dir=str(material_output_dir),
                texture_output_dir=str(texture_output_dir),
                shader_output_dir=str(shader_output_dir),
                export_texture_images=export_texture_assets,
            )

            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            summary = payload.get("summary", {})
            tokens = []
            for key in (
                "material_count",
                "texture_count",
                "shader_count"
            ):
                if key in summary:
                    tokens.append(f"{key}={summary.get(key, 0)}")

            print(f"report saved: {output_path}")
            artifacts = payload.get("artifacts", {})
            if isinstance(artifacts, dict):
                material_info = artifacts.get("materials", {})
                texture_info = artifacts.get("textures", {})
                shader_info = artifacts.get("shaders", {})
                if isinstance(material_info, dict) and material_info.get("index"):
                    print(f"materials index: {material_info.get('index')}")
                if isinstance(texture_info, dict) and texture_info.get("index"):
                    print(f"textures index: {texture_info.get('index')}")
                if isinstance(shader_info, dict) and shader_info.get("index"):
                    print(f"shaders index: {shader_info.get('index')}")
            print("summary: " + ", ".join(tokens) if tokens else "summary: (empty)")

        except Exception as exc:
            print(f"rdc_parse_task error: {exc}")


@task_manager.manager.register
class ParseRdcTaskCompat(ParseRdcTask):
    """Compatibility alias for legacy task id parse_rdc."""

    TASK_ID = "parse_rdc"
