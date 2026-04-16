from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from parse.modules.material_module import MaterialModule

from . import task_manager


def _resolve_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (Path.cwd() / path).resolve()


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    safe = safe.strip("._")
    return safe or "compare"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_str_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    items = []
    for value in values:
        text = str(value or "").strip()
        if text:
            items.append(text)
    return sorted(set(items))


def _canonical_shader_set(shader_set: Dict[str, str]) -> Dict[str, str]:
    canonical: Dict[str, str] = {}
    for stage in sorted(shader_set):
        stage_text = str(stage or "").strip()
        shader_key = str(shader_set.get(stage, "") or "").strip()
        if stage_text and shader_key:
            canonical[stage_text] = shader_key
    return canonical


def _normalize_shader_sets(material_payload: Dict[str, Any]) -> List[Dict[str, str]]:
    shader_sets_raw = material_payload.get("shader_sets")
    shader_sets: List[Dict[str, str]] = []
    if isinstance(shader_sets_raw, list):
        for shader_set in shader_sets_raw:
            if not isinstance(shader_set, dict):
                continue
            canonical = _canonical_shader_set(shader_set)
            if canonical:
                shader_sets.append(canonical)

    if shader_sets:
        seen = set()
        deduped = []
        for shader_set in shader_sets:
            token = json.dumps(shader_set, ensure_ascii=False, sort_keys=True)
            if token in seen:
                continue
            seen.add(token)
            deduped.append(shader_set)
        deduped.sort(key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
        return deduped

    stage_map: Dict[str, str] = {}
    for shader_row in material_payload.get("shaders", []) or []:
        if not isinstance(shader_row, dict):
            continue
        stage = str(shader_row.get("stage", "") or "").strip()
        shader_key = str(shader_row.get("shader_key", "") or "").strip()
        if stage and shader_key and stage not in stage_map:
            stage_map[stage] = shader_key
    if stage_map:
        return [_canonical_shader_set(stage_map)]
    return []


def _resolve_entry_path(target: Path) -> Path:
    if target.is_file():
        return target
    return target / "rdc_entry.json"


def _load_material_summary_map(target: Path) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any], Path]:
    entry_path = _resolve_entry_path(target)
    if not entry_path.exists():
        raise FileNotFoundError(f"rdc_entry.json not found: {entry_path}")

    entry_payload = _load_json(entry_path)
    artifacts = entry_payload.get("artifacts", {})
    materials_artifact = artifacts.get("materials", {}) if isinstance(artifacts, dict) else {}
    index_rel_path = str(materials_artifact.get("index", "") or "").strip()
    if not index_rel_path:
        raise RuntimeError(f"materials.index missing in {entry_path}")

    base_dir = entry_path.parent
    index_path = base_dir / index_rel_path
    if not index_path.exists():
        raise FileNotFoundError(f"material index not found: {index_path}")

    index_rows = _load_json(index_path)
    if not isinstance(index_rows, list):
        raise RuntimeError(f"invalid material index format: {index_path}")

    summary_map: Dict[str, Dict[str, Any]] = {}
    for row in index_rows:
        if not isinstance(row, dict):
            continue
        material_id = str(row.get("id", "") or "").strip()
        material_rel_path = str(row.get("path", "") or "").strip()
        if not material_id or not material_rel_path:
            continue

        material_path = base_dir / material_rel_path
        if not material_path.exists():
            continue
        material_payload = _load_json(material_path)
        if not isinstance(material_payload, dict):
            continue

        material_instance_names = _normalize_str_list(material_payload.get("material_instance_names", []))
        material_instance_name = str(material_payload.get("material_instance_name", "") or "").strip()
        if not material_instance_name and material_instance_names:
            material_instance_name = material_instance_names[0]

        mesh_names = _normalize_str_list(material_payload.get("mesh_names", []))
        pass_channels = _normalize_str_list(material_payload.get("pass_channels", []))
        shader_sets = _normalize_shader_sets(material_payload)
        content_signature = str(material_payload.get("content_signature", "") or "").strip()
        if not content_signature:
            content_signature = MaterialModule.build_content_signature(
                mesh_names=mesh_names,
                pass_channels=pass_channels,
                shader_sets=shader_sets,
            )

        summary_map[material_id] = {
            "material_key": material_id,
            "material_instance_name": material_instance_name,
            "mesh_names": mesh_names,
            "pass_channels": pass_channels,
            "shader_sets": shader_sets,
            "content_signature": content_signature,
        }

    return summary_map, entry_payload, entry_path


def _diff_str_list(left: List[str], right: List[str]) -> Dict[str, List[str]]:
    left_set = set(left)
    right_set = set(right)
    return {
        "added": sorted(right_set - left_set),
        "removed": sorted(left_set - right_set),
    }


def _diff_shader_sets(left: List[Dict[str, str]], right: List[Dict[str, str]]) -> Dict[str, List[Dict[str, str]]]:
    left_map = {json.dumps(item, ensure_ascii=False, sort_keys=True): item for item in left}
    right_map = {json.dumps(item, ensure_ascii=False, sort_keys=True): item for item in right}
    added_keys = sorted(set(right_map) - set(left_map))
    removed_keys = sorted(set(left_map) - set(right_map))
    return {
        "added": [right_map[key] for key in added_keys],
        "removed": [left_map[key] for key in removed_keys],
    }


def _build_default_output_path(
    left_entry: Dict[str, Any], right_entry: Dict[str, Any], left_path: Path, right_path: Path
) -> Path:
    left_name = str(left_entry.get("capture_file", "") or left_path.parent.name or "left")
    right_name = str(right_entry.get("capture_file", "") or right_path.parent.name or "right")
    file_name = f"{_safe_name(left_name)}__vs__{_safe_name(right_name)}.json"
    out_dir = _resolve_path("output") / "material_compare"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / file_name


@task_manager.manager.register
class MaterialCompareTask:
    """Compare material summaries between two parsed capture outputs."""

    TASK_ID = "rdc_material_compare"

    def execute(self, args, params):
        try:
            left_value = str(params.get("left", "") or "").strip()
            right_value = str(params.get("right", "") or "").strip()
            if not left_value or not right_value:
                raise RuntimeError("missing required params: left, right")

            left_target = _resolve_path(left_value)
            right_target = _resolve_path(right_value)

            left_map, left_entry, left_entry_path = _load_material_summary_map(left_target)
            right_map, right_entry, right_entry_path = _load_material_summary_map(right_target)

            left_keys = set(left_map)
            right_keys = set(right_map)
            added_keys = sorted(right_keys - left_keys)
            removed_keys = sorted(left_keys - right_keys)
            common_keys = sorted(left_keys & right_keys)

            unchanged = 0
            changed_rows: List[Dict[str, Any]] = []
            for material_key in common_keys:
                left_item = left_map[material_key]
                right_item = right_map[material_key]
                if left_item.get("content_signature") == right_item.get("content_signature"):
                    unchanged += 1
                    continue

                mesh_diff = _diff_str_list(left_item.get("mesh_names", []), right_item.get("mesh_names", []))
                pass_diff = _diff_str_list(left_item.get("pass_channels", []), right_item.get("pass_channels", []))
                shader_set_diff = _diff_shader_sets(left_item.get("shader_sets", []), right_item.get("shader_sets", []))

                changed_rows.append(
                    {
                        "material_key": material_key,
                        "material_instance_name": right_item.get("material_instance_name")
                        or left_item.get("material_instance_name", ""),
                        "left_content_signature": left_item.get("content_signature", ""),
                        "right_content_signature": right_item.get("content_signature", ""),
                        "changes": {
                            "mesh_names": mesh_diff,
                            "pass_channels": pass_diff,
                            "shader_sets": shader_set_diff,
                        },
                    }
                )

            report = {
                "left": {
                    "entry": str(left_entry_path),
                    "capture_file": str(left_entry.get("capture_file", "") or ""),
                    "material_count": len(left_keys),
                },
                "right": {
                    "entry": str(right_entry_path),
                    "capture_file": str(right_entry.get("capture_file", "") or ""),
                    "material_count": len(right_keys),
                },
                "summary": {
                    "added": len(added_keys),
                    "removed": len(removed_keys),
                    "changed": len(changed_rows),
                    "unchanged": unchanged,
                    "matched": len(common_keys),
                },
                "added_materials": [right_map[key] for key in added_keys],
                "removed_materials": [left_map[key] for key in removed_keys],
                "changed_materials": changed_rows,
            }

            output_value = str(params.get("out", "") or "").strip()
            if output_value:
                output_path = _resolve_path(output_value)
                output_path.parent.mkdir(parents=True, exist_ok=True)
            else:
                output_path = _build_default_output_path(left_entry, right_entry, left_entry_path, right_entry_path)

            output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

            print(f"rdc_material_compare done: {output_path}")
            summary = report.get("summary", {})
            print(
                "rdc_material_compare summary: "
                f"added={summary.get('added', 0)}, "
                f"removed={summary.get('removed', 0)}, "
                f"changed={summary.get('changed', 0)}, "
                f"unchanged={summary.get('unchanged', 0)}"
            )
        except Exception as exc:
            task_manager.emit_error_output(exc)
