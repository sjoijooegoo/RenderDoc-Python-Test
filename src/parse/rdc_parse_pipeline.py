from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import renderdoc as rd

from . import rdc_utils
from . import utils
from .capture_loader import load_capture
from .modules import MaterialModule, PassModule, ShaderModule, TextureModule
from .modules.io_utils import sha256_file

SCHEMA_VERSION = "1.5.0"
PARSER_VERSION = "rdc_parse_v1.5.0"


class RdcParsePipeline:
    """Parse one .rdc file and extract material/shader-focused data."""

    def __init__(self, filename: str):
        self.filename = filename
        self.cap: Optional[rd.CaptureFile] = None
        self.controller: Optional[rd.ReplayController] = None
        self._resource_names: Dict[str, str] = {}
        self._texture_ids: Set[str] = set()
        self._texture_desc_map: Dict[str, Any] = {}

        self.shader_module = ShaderModule()
        self.texture_module = TextureModule()
        self.material_module = MaterialModule()
        self.pass_module = PassModule()

    def _log(self, message: str) -> None:
        print(f"[rdc_parse] {message}")

    def load(self) -> None:
        load_start = time.perf_counter()
        self.cap, self.controller = load_capture(self.filename)
        self._resource_names = self._build_resource_name_map()
        self._texture_ids = TextureModule.build_texture_id_set(self.controller)
        self._texture_desc_map = TextureModule.build_texture_desc_map(self.controller)

        self.shader_module.set_resource_names(self._resource_names)
        self.material_module.set_resource_names(self._resource_names)
        self.texture_module.set_capture_context(
            self.controller,
            self._resource_names,
            self._texture_ids,
            self._texture_desc_map,
        )
        self.texture_module.set_logger(self._log)
        self.pass_module.set_controller(self.controller)
        self._log(
            "load done: "
            f"resources={len(self._resource_names)}, textures={len(self._texture_ids)}, "
            f"elapsed={time.perf_counter() - load_start:.2f}s"
        )

    def shutdown(self) -> None:
        if self.controller is not None:
            try:
                self.controller.Shutdown()
            except Exception:
                pass
            self.controller = None

        if self.cap is not None:
            try:
                self.cap.Shutdown()
            except Exception:
                pass
            self.cap = None

    def __enter__(self) -> "RdcParsePipeline":
        self.load()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.shutdown()

    def _build_resource_name_map(self) -> Dict[str, str]:
        if self.controller is None:
            return {}

        name_map: Dict[str, str] = {}
        try:
            for res in self.controller.GetResources():
                rid = str(res.resourceId)
                if rid:
                    name_map[rid] = res.name or ""

                for derived in res.derivedResources or []:
                    if derived is not None:
                        name_map.setdefault(str(derived), res.name or "")
        except Exception:
            return name_map

        return name_map

    def _capture_id(self) -> str:
        try:
            capture_path = Path(self.filename).resolve()
            stat = capture_path.stat()
            token = f"{capture_path.name}|{stat.st_size}|{int(stat.st_mtime_ns)}"
        except Exception:
            token = Path(self.filename).name
        return f"cap:{hashlib.md5(token.encode('utf-8')).hexdigest()}"

    def _build_index_entries(
        self, pairs: List[Tuple[str, str]], base_dir: Optional[Path]
    ) -> List[Dict[str, str]]:
        entries: List[Dict[str, str]] = []
        for item_id, rel_path in pairs:
            entry: Dict[str, str] = {"id": item_id, "path": rel_path}
            if base_dir is not None:
                abs_path = (base_dir / rel_path).resolve()
                if abs_path.exists() and abs_path.is_file():
                    entry["sha256"] = sha256_file(abs_path)
            entries.append(entry)
        return entries

    def _write_index_file(
        self, dir_path: Optional[Path], items: List[Dict[str, str]], file_name: str = "index.json"
    ) -> Optional[str]:
        if dir_path is None:
            return None
        target = dir_path / file_name
        target.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        return target.relative_to(dir_path.parent).as_posix()

    def _extract_sampler_ids(self, state: rd.PipeState, shader_stages: List[rd.ShaderStage]) -> List[str]:
        sampler_ids: Set[str] = set()
        for stage in shader_stages:
            try:
                samplers = state.GetSamplers(stage, True)
            except Exception:
                continue

            for used in samplers or []:
                descriptor = getattr(used, "descriptor", None)
                if descriptor is not None:
                    rid = utils.normalize_resource_id(getattr(descriptor, "secondary", None))
                    if rid:
                        sampler_ids.add(rid)

                sampler_desc = getattr(used, "sampler", None)
                if sampler_desc is not None:
                    for attr in ("object", "ycbcrSampler"):
                        rid = utils.normalize_resource_id(getattr(sampler_desc, attr, None))
                        if rid:
                            sampler_ids.add(rid)

        return sorted(sampler_ids)

    def _parse_revision1(
        self,
        include_source: bool = False,
    ) -> Dict[str, Any]:
        if self.controller is None:
            raise RuntimeError("Parser is not loaded")

        material_map: Dict[str, Dict[str, Any]] = {}
        shader_registry: Dict[str, Dict[str, Any]] = {}
        pass_map: Dict[str, Dict[str, Any]] = {}
        used_texture_ids: Set[str] = set()
        parse_start = time.perf_counter()

        pipeline_type = "Unknown"
        try:
            api_props = self.controller.GetAPIProperties()
            pipeline_type = utils.enum_name(getattr(api_props, "pipelineType", None)) or "Unknown"
        except Exception:
            pass

        shader_stages = self.shader_module.shader_stages()
        all_actions = rdc_utils.list_all_actions(self.controller)
        draw_actions = [action for action in all_actions if rdc_utils.is_draw_or_dispatch(action)]
        self._log(
            "scan start: "
            f"total_actions={len(all_actions)}, draw_or_dispatch_actions={len(draw_actions)}, "
            f"include_source={include_source}, export_texture_images={self.texture_module.export_texture_images}"
        )

        for index, action in enumerate(draw_actions, start=1):
            action_start = time.perf_counter()

            self.controller.SetFrameEvent(action.eventId, True)
            state = self.controller.GetPipelineState()

            shader_items = self.shader_module.extract_shaders(state, include_source=include_source)
            shader_keys = sorted(set(item["shader_key"] for item in shader_items))

            texture_ids = self.texture_module.extract_texture_ids(state, shader_stages)
            used_texture_ids.update(texture_ids)
            sampler_ids = self._extract_sampler_ids(state, shader_stages)
            used_resource_ids = self.texture_module.extract_used_resource_ids(state, shader_stages)
            constant_layout_tokens = ShaderModule.extract_constant_layout_tokens_from_shaders(shader_items)

            base_features = self.material_module.build_base_features(
                texture_ids,
                sampler_ids,
                constant_layout_tokens,
                self.texture_module.texture_compare_key,
            )
            material_base_key = self.material_module.build_material_base_key(base_features)

            pass_features = self.pass_module.extract_pass_features(action, state, pipeline_type)
            pass_key = str(pass_features.get("pass_key", ""))
            marker_context = PassModule.extract_marker_context(pass_features.get("marker_path", ""))
            pass_channel = marker_context.get("pass_channel", "")
            material_instance_name = marker_context.get("material_instance_name", "")
            mesh_name = marker_context.get("mesh_name", "")
            marker_path = str(pass_features.get("marker_path", "") or "")

            # Keep these keys for future expansion (currently not exported).
            mesh_key = self.pass_module.build_mesh_key(action, state)
            lighting_key = self.pass_module.build_lighting_key(
                used_resource_ids, constant_layout_tokens, self._resource_names
            )
            _ = utils.make_signature([pass_key, mesh_key, lighting_key], "ctx")

            material_entry = material_map.get(material_base_key)
            if material_entry is None:
                material_entry = {
                    "material_base_key": material_base_key,
                    "base_features": base_features,
                    "_texture_id_set": set(),
                    "_shader_key_set": set(),
                    "_pass_channel_set": set(),
                    "_material_instance_name_set": set(),
                    "_mesh_name_set": set(),
                    "_sample_marker_path_set": set(),
                    "_usage_count": 0,
                }
                material_map[material_base_key] = material_entry

            material_entry["_usage_count"] += 1
            material_entry["_texture_id_set"].update(texture_ids)
            material_entry["_shader_key_set"].update(shader_keys)
            if pass_channel:
                material_entry["_pass_channel_set"].add(pass_channel)
            if material_instance_name:
                material_entry["_material_instance_name_set"].add(material_instance_name)
            if mesh_name:
                material_entry["_mesh_name_set"].add(mesh_name)
            if marker_path and marker_path != "root":
                marker_set = material_entry["_sample_marker_path_set"]
                if len(marker_set) < 20:
                    marker_set.add(marker_path)

            pass_entry = pass_map.get(pass_key)
            if pass_entry is None:
                pass_entry = {
                    "pass_key": pass_key,
                    "pass_features": {
                        "pipeline_type": pass_features.get("pipeline_type", "Unknown"),
                        "marker_path": pass_features.get("marker_path", "root"),
                        "pass_channel": pass_channel,
                        "output_resource_ids": pass_features.get("output_resource_ids", []),
                        "depth_output_resource_id": pass_features.get("depth_output_resource_id", ""),
                        "pipeline_object": pass_features.get("pipeline_object", ""),
                    },
                    "usage_count": 0,
                    "_material_key_set": set(),
                    "_material_instance_name_set": set(),
                    "_mesh_name_set": set(),
                }
                pass_map[pass_key] = pass_entry

            pass_entry["usage_count"] += 1
            pass_entry["_material_key_set"].add(material_base_key)
            if material_instance_name:
                pass_entry["_material_instance_name_set"].add(material_instance_name)
            if mesh_name:
                pass_entry["_mesh_name_set"].add(mesh_name)

            if self.texture_module.output_dir is not None:
                for texture_id in texture_ids:
                    self.texture_module.ensure_texture_export(texture_id)

            for item in shader_items:
                ShaderModule.register_shader(shader_registry, item)

            action_elapsed = time.perf_counter() - action_start
            if action_elapsed >= 2.0:
                self._log(
                    "slow action: "
                    f"index={index}/{len(draw_actions)}, event_id={action.eventId}, "
                    f"elapsed={action_elapsed:.2f}s, marker_path={marker_path or 'root'}"
                )

            if index == 1 or index % 25 == 0 or index == len(draw_actions):
                self._log(
                    "scan progress: "
                    f"{index}/{len(draw_actions)} actions, "
                    f"materials={len(material_map)}, passes={len(pass_map)}, "
                    f"shaders={len(shader_registry)}, used_textures={len(used_texture_ids)}, "
                    f"elapsed={time.perf_counter() - parse_start:.2f}s"
                )

        self._log(f"scan done: elapsed={time.perf_counter() - parse_start:.2f}s")

        material_rows: List[Tuple[Dict[str, Any], int]] = []
        for material_entry in material_map.values():
            material_payload = {
                "material_base_key": material_entry["material_base_key"],
                "usage_count": int(material_entry.get("_usage_count", 0) or 0),
                "material_instance_names": sorted(material_entry.get("_material_instance_name_set", set())),
                "pass_channels": sorted(material_entry.get("_pass_channel_set", set())),
                "mesh_names": sorted(material_entry.get("_mesh_name_set", set())),
                "sample_marker_paths": sorted(material_entry.get("_sample_marker_path_set", set())),
                "texture_json_paths": [
                    self.texture_module.texture_json_path(texture_id) or texture_id
                    for texture_id in sorted(material_entry["_texture_id_set"])
                ],
                "shader_json_paths": [
                    self.shader_module.shader_json_path(shader_key) or shader_key
                    for shader_key in sorted(material_entry["_shader_key_set"])
                ],
            }
            material_rows.append((material_payload, material_entry["_usage_count"]))

        material_rows.sort(key=lambda item: item[1], reverse=True)
        material_pairs: List[Tuple[str, str]] = []
        material_path_map: Dict[str, str] = {}
        material_persist_start = time.perf_counter()
        self._log(f"persist materials start: count={len(material_rows)}")
        for material_payload, _usage in material_rows:
            material_key = str(material_payload.get("material_base_key", ""))
            material_path = self.material_module.persist_material_record(material_key, material_payload)
            if material_path:
                material_pairs.append((material_key, material_path))
                material_path_map[material_key] = material_path
        self._log(
            f"persist materials done: count={len(material_pairs)}, "
            f"elapsed={time.perf_counter() - material_persist_start:.2f}s"
        )

        artifacts: Dict[str, Any] = {}
        if self.material_module.output_dir is not None:
            material_index_entries = self._build_index_entries(material_pairs, self.material_module.output_base_dir)
            index_path = self._write_index_file(
                self.material_module.output_dir,
                material_index_entries,
                file_name="rdc_material_index.json",
            )
            if index_path:
                artifacts["materials"] = {
                    "index": index_path,
                    "count": len(material_index_entries),
                }

        if self.texture_module.output_dir is not None:
            texture_pairs: List[Tuple[str, str]] = []
            texture_export_error_count = 0
            texture_stage_start = time.perf_counter()
            self._log(f"persist textures start: count={len(used_texture_ids)}")
            for index, texture_id in enumerate(sorted(used_texture_ids), start=1):
                texture_record = self.texture_module.ensure_texture_export(texture_id)
                if texture_record.get("export_error"):
                    texture_export_error_count += 1
                texture_path = self.texture_module.persist_texture_record(texture_id, texture_record)
                if texture_path:
                    texture_pairs.append((str(texture_record.get("texture_compare_key", texture_id)), texture_path))
                if index == 1 or index % 50 == 0 or index == len(used_texture_ids):
                    self._log(
                        "persist textures progress: "
                        f"{index}/{len(used_texture_ids)}, errors={texture_export_error_count}, "
                        f"elapsed={time.perf_counter() - texture_stage_start:.2f}s"
                    )

            texture_index_entries = self._build_index_entries(texture_pairs, self.texture_module.output_base_dir)
            index_path = self._write_index_file(
                self.texture_module.output_dir,
                texture_index_entries,
                file_name="rdc_texture_index.json",
            )
            if index_path:
                artifacts["textures"] = {
                    "index": index_path,
                    "count": len(texture_index_entries),
                }
            self._log(
                f"persist textures done: count={len(texture_pairs)}, "
                f"errors={texture_export_error_count}, "
                f"elapsed={time.perf_counter() - texture_stage_start:.2f}s"
            )

        if self.shader_module.output_dir is not None:
            shader_rows = sorted(
                shader_registry.values(),
                key=lambda x: (x.get("usage_count", 0), x.get("source_line_count", 0)),
                reverse=True,
            )
            shader_pairs: List[Tuple[str, str]] = []
            shader_stage_start = time.perf_counter()
            self._log(f"persist shaders start: count={len(shader_rows)}")
            for index, shader_payload in enumerate(shader_rows, start=1):
                shader_path = self.shader_module.persist_shader_record(shader_payload)
                if shader_path:
                    shader_pairs.append((str(shader_payload.get("shader_key", "")), shader_path))
                if index == 1 or index % 50 == 0 or index == len(shader_rows):
                    self._log(
                        "persist shaders progress: "
                        f"{index}/{len(shader_rows)}, elapsed={time.perf_counter() - shader_stage_start:.2f}s"
                    )

            shader_index_entries = self._build_index_entries(shader_pairs, self.shader_module.output_base_dir)
            index_path = self._write_index_file(
                self.shader_module.output_dir,
                shader_index_entries,
                file_name="rdc_shader_index.json",
            )
            if index_path:
                artifacts["shaders"] = {
                    "index": index_path,
                    "count": len(shader_index_entries),
                }
            self._log(
                f"persist shaders done: count={len(shader_pairs)}, "
                f"elapsed={time.perf_counter() - shader_stage_start:.2f}s"
            )

        if self.pass_module.output_dir is not None:
            pass_rows = sorted(pass_map.values(), key=lambda x: x.get("usage_count", 0), reverse=True)
            pass_pairs: List[Tuple[str, str]] = []
            pass_stage_start = time.perf_counter()
            self._log(f"persist passes start: count={len(pass_rows)}")
            for index, pass_entry in enumerate(pass_rows, start=1):
                pass_key = str(pass_entry.get("pass_key", ""))
                material_paths = [
                    material_path_map[mat_key]
                    for mat_key in sorted(pass_entry.get("_material_key_set", set()))
                    if mat_key in material_path_map
                ]
                pass_payload = {
                    "pass_key": pass_key,
                    "pass_features": pass_entry.get("pass_features", {}),
                    "usage_count": int(pass_entry.get("usage_count", 0) or 0),
                    "material_json_paths": material_paths,
                    "material_instance_names": sorted(
                        pass_entry.get("_material_instance_name_set", set())
                    ),
                    "mesh_names": sorted(pass_entry.get("_mesh_name_set", set())),
                }
                pass_path = self.pass_module.persist_pass_record(pass_payload)
                if pass_path:
                    pass_pairs.append((pass_key, pass_path))
                if index == 1 or index % 50 == 0 or index == len(pass_rows):
                    self._log(
                        "persist passes progress: "
                        f"{index}/{len(pass_rows)}, elapsed={time.perf_counter() - pass_stage_start:.2f}s"
                    )

            pass_index_entries = self._build_index_entries(pass_pairs, self.pass_module.output_base_dir)
            index_path = self._write_index_file(
                self.pass_module.output_dir,
                pass_index_entries,
                file_name="rdc_pass_index.json",
            )
            if index_path:
                artifacts["passes"] = {
                    "index": index_path,
                    "count": len(pass_index_entries),
                }
            self._log(
                f"persist passes done: count={len(pass_pairs)}, "
                f"elapsed={time.perf_counter() - pass_stage_start:.2f}s"
            )

        self._log(f"parse done: total_elapsed={time.perf_counter() - parse_start:.2f}s")

        return {
            "schema_version": SCHEMA_VERSION,
            "capture_file": Path(self.filename).name,
            "capture_id": self._capture_id(),
            "artifacts": artifacts,
        }

    def _parse_legacy(self, include_source: bool = False) -> Dict[str, Any]:
        if self.controller is None:
            raise RuntimeError("Parser is not loaded")

        shader_registry: Dict[str, Dict[str, Any]] = {}
        material_map: Dict[str, Dict[str, Any]] = {}

        stage_line_counts_by_usage: Dict[str, int] = {}
        total_shader_lines_by_usage = 0

        shader_stages = self.shader_module.shader_stages()

        for action in rdc_utils.list_all_actions(self.controller):
            if not rdc_utils.is_draw_or_dispatch(action):
                continue

            self.controller.SetFrameEvent(action.eventId, True)
            state = self.controller.GetPipelineState()

            shaders = self.shader_module.extract_shaders(state, include_source)
            texture_ids = self.texture_module.extract_texture_ids(state, shader_stages)
            shader_keys = sorted(set(item["shader_key"] for item in shaders))

            for item in shaders:
                shader_key = item["shader_key"]
                entry = shader_registry.get(shader_key)
                if entry is None:
                    entry = {
                        "shader_key": shader_key,
                        "stage": item.get("stage", ""),
                        "entry_point": item.get("entry_point", ""),
                        "resource_id": utils.safe_resource_id(item.get("resource")),
                        "resource_name": (item.get("resource") or {}).get("name", ""),
                        "source_md5": item.get("source_md5", ""),
                        "source_line_count": int(item.get("source_line_count", 0)),
                        "source_file_count": int(item.get("source_file_count", 0)),
                        "source_files": item.get("source_files", []),
                        "usage_count": 0,
                    }
                    shader_registry[shader_key] = entry

                entry["usage_count"] += 1
                stage = item.get("stage", "") or "Unknown"
                line_count = int(item.get("source_line_count", 0))
                stage_line_counts_by_usage[stage] = stage_line_counts_by_usage.get(stage, 0) + line_count
                total_shader_lines_by_usage += line_count

            material_key = f"S:{'|'.join(shader_keys)}||T:{'|'.join(texture_ids)}"
            material_entry = material_map.get(material_key)
            if material_entry is None:
                material_entry = {
                    "material_key": material_key,
                    "shader_keys": shader_keys,
                    "texture_ids": texture_ids,
                    "usage_count": 0,
                }
                material_map[material_key] = material_entry

            material_entry["usage_count"] += 1

        shaders = []
        stage_line_counts_unique: Dict[str, int] = {}
        for shader in shader_registry.values():
            shaders.append(shader)
            stage = shader.get("stage") or "Unknown"
            stage_line_counts_unique[stage] = stage_line_counts_unique.get(stage, 0) + int(
                shader.get("source_line_count", 0)
            )

        shaders.sort(key=lambda x: (x.get("source_line_count", 0), x.get("usage_count", 0)), reverse=True)
        materials = sorted(material_map.values(), key=lambda x: x.get("usage_count", 0), reverse=True)

        summary = {
            "shader_count": len(shaders),
            "material_count": len(materials),
            "shader_total_lines_unique": sum(int(x.get("source_line_count", 0)) for x in shaders),
            "shader_total_lines_by_usage": total_shader_lines_by_usage,
            "shader_stage_line_counts_unique": dict(sorted(stage_line_counts_unique.items())),
            "shader_stage_line_counts_by_usage": dict(sorted(stage_line_counts_by_usage.items())),
            "top_shaders_by_lines": [
                {
                    "shader_key": x.get("shader_key"),
                    "stage": x.get("stage"),
                    "entry_point": x.get("entry_point"),
                    "source_line_count": x.get("source_line_count", 0),
                    "usage_count": x.get("usage_count", 0),
                }
                for x in shaders[:20]
            ],
        }

        payload: Dict[str, Any] = {
            "capture_file": Path(self.filename).name,
            "summary": summary,
            "materials": materials,
            "shaders": shaders,
        }

        if include_source and self.shader_module.source_output_dir is not None:
            shader_dir = (
                self.shader_module.source_output_dir.relative_to(self.shader_module.source_output_base_dir).as_posix()
                if self.shader_module.source_output_base_dir is not None
                else str(self.shader_module.source_output_dir)
            )
            payload["artifacts"] = {"shader_sources_dir": shader_dir}

        return payload

    def parse(
        self,
        include_source: bool = False,
        schema: str = "1",
        source_output_dir: Optional[str] = None,
        material_output_dir: Optional[str] = None,
        texture_output_dir: Optional[str] = None,
        shader_output_dir: Optional[str] = None,
        pass_output_dir: Optional[str] = None,
        export_texture_images: bool = True,
    ) -> Dict[str, Any]:
        normalized = str(schema or "1").strip().lower()
        self.texture_module.set_export_texture_images(bool(export_texture_images))

        if normalized in {"1", "v1", "rev1", "first"}:
            self.shader_module.configure_shader_output_dir(shader_output_dir)
            self.shader_module.configure_source_output_dir(shader_output_dir if include_source else None)
            self.material_module.configure_output_dir(material_output_dir)
            self.texture_module.configure_output_dir(texture_output_dir)
            self.pass_module.configure_output_dir(pass_output_dir)
        else:
            self.shader_module.configure_shader_output_dir(None)
            self.shader_module.configure_source_output_dir(source_output_dir if include_source else None)
            self.material_module.configure_output_dir(None)
            self.texture_module.configure_output_dir(None)
            self.pass_module.configure_output_dir(None)

        if normalized in {"1", "v1", "rev1", "first"}:
            return self._parse_revision1(
                include_source=include_source,
            )

        return self._parse_legacy(include_source=include_source)


def parse_capture_rdc(
    filename: str,
    include_source: bool = False,
    schema: str = "1",
    source_output_dir: Optional[str] = None,
    material_output_dir: Optional[str] = None,
    texture_output_dir: Optional[str] = None,
    shader_output_dir: Optional[str] = None,
    pass_output_dir: Optional[str] = None,
    export_texture_images: bool = True,
) -> Dict[str, Any]:
    with RdcParsePipeline(filename) as parser:
        return parser.parse(
            include_source=include_source,
            schema=schema,
            source_output_dir=source_output_dir,
            material_output_dir=material_output_dir,
            texture_output_dir=texture_output_dir,
            shader_output_dir=shader_output_dir,
            pass_output_dir=pass_output_dir,
            export_texture_images=export_texture_images,
        )


# Backward compatibility aliases
MaterialShaderParser = RdcParsePipeline
parse_capture_material_shader = parse_capture_rdc
