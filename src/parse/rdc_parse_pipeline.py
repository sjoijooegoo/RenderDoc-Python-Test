from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
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
        self._texture_catalog_ready = False

        self.shader_module = ShaderModule()
        self.texture_module = TextureModule()
        self.material_module = MaterialModule()
        self.pass_module = PassModule()

    def _log(self, message: str) -> None:
        print(f"[rdc_parse] {message}")

    def _run_text_command(self, command: List[str], timeout: int = 10) -> str:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except Exception:
            return ""

        output = (completed.stdout or "").strip()
        if output:
            return output
        return (completed.stderr or "").strip()

    def _system_gpu_lines(self) -> List[str]:
        if os.name == "nt":
            output = self._run_text_command(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_VideoController | "
                    "Select-Object Name,DriverVersion,Status | ConvertTo-Json -Compress",
                ],
                timeout=15,
            )
            if output:
                try:
                    raw = json.loads(output)
                    items = raw if isinstance(raw, list) else [raw]
                    lines: List[str] = []
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        name = str(item.get("Name", "") or "")
                        driver = str(item.get("DriverVersion", "") or "")
                        status = str(item.get("Status", "") or "")
                        token = ", ".join(
                            part
                            for part in [
                                name,
                                f"driver={driver}" if driver else "",
                                f"status={status}" if status else "",
                            ]
                            if part
                        )
                        if token:
                            lines.append(token)
                    if lines:
                        return lines
                except Exception:
                    pass

        if sys.platform.startswith("linux"):
            output = self._run_text_command(["sh", "-lc", "lspci | grep -iE 'vga|3d|display'"], timeout=10)
            if output:
                return [line.strip() for line in output.splitlines() if line.strip()]

        return []

    def _api_properties_snapshot(self) -> Dict[str, Any]:
        if self.controller is None:
            return {}

        try:
            props = self.controller.GetAPIProperties()
        except Exception:
            return {}

        snapshot: Dict[str, Any] = {}
        for name in (
            "pipelineType",
            "vendor",
            "localRenderer",
            "remoteReplay",
            "degraded",
            "shaderDebugging",
            "pixelHistory",
            "rgpCapture",
        ):
            value = getattr(props, name, None)
            if value is None:
                continue
            enum_name = utils.enum_name(value)
            if enum_name:
                snapshot[name] = enum_name
                continue
            try:
                value = value.Name()
            except Exception:
                pass
            snapshot[name] = value
        return snapshot

    def _log_environment_diagnostics(self) -> None:
        capture_path = Path(self.filename)
        try:
            capture_size = capture_path.stat().st_size
        except Exception:
            capture_size = 0

        env_info = {
            "host": platform.node(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "session": os.environ.get("SESSIONNAME", ""),
            "user": os.environ.get("USERNAME", "") or os.environ.get("USER", ""),
            "ci": os.environ.get("CI", ""),
            "computer": os.environ.get("COMPUTERNAME", ""),
            "capture_file": capture_path.name,
            "capture_size": capture_size,
        }
        self._log("env diagnostics: " + json.dumps(env_info, ensure_ascii=False))

        gpu_lines = self._system_gpu_lines()
        if gpu_lines:
            for index, line in enumerate(gpu_lines, start=1):
                self._log(f"gpu[{index}]: {line}")
        else:
            self._log("gpu: unavailable")

        api_info = self._api_properties_snapshot()
        if api_info:
            self._log("replay diagnostics: " + json.dumps(api_info, ensure_ascii=False, default=str))
        else:
            self._log("replay diagnostics: unavailable")

    def load(self) -> None:
        load_start = time.perf_counter()
        self.cap, self.controller = load_capture(self.filename)
        self._resource_names = self._build_resource_name_map()
        self._texture_ids = set()
        self._texture_desc_map = {}
        self._texture_catalog_ready = False

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
        self._log_environment_diagnostics()
        self._log(
            "load done: "
            f"resources={len(self._resource_names)}, textures={len(self._texture_ids)}, "
            f"elapsed={time.perf_counter() - load_start:.2f}s"
        )

    def _ensure_texture_catalog(self) -> None:
        if self._texture_catalog_ready:
            return
        if self.controller is None:
            return

        self._texture_ids = TextureModule.build_texture_id_set(self.controller)
        self._texture_desc_map = TextureModule.build_texture_desc_map(self.controller)
        self._texture_catalog_ready = True
        self.texture_module.set_capture_context(
            self.controller,
            self._resource_names,
            self._texture_ids,
            self._texture_desc_map,
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

    def _write_json_file(self, dir_path: Optional[Path], payload: Any, file_name: str) -> Optional[str]:
        if dir_path is None:
            return None
        target = dir_path / file_name
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target.relative_to(dir_path.parent).as_posix()

    @staticmethod
    def _build_stage_shader_map(shader_items: List[Dict[str, Any]]) -> Dict[str, str]:
        stage_to_keys: Dict[str, Set[str]] = {}
        for shader_item in shader_items:
            stage = str(shader_item.get("stage", "") or "").strip()
            shader_key = str(shader_item.get("shader_key", "") or "").strip()
            if not stage or not shader_key:
                continue
            stage_to_keys.setdefault(stage, set()).add(shader_key)

        stage_shader_map: Dict[str, str] = {}
        for stage in sorted(stage_to_keys):
            shader_keys = sorted(stage_to_keys[stage])
            if shader_keys:
                stage_shader_map[stage] = shader_keys[0]
        return stage_shader_map

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

    def _select_final_frame_output(self, draw_actions: List[rd.ActionDescription]) -> Optional[Tuple[rd.ActionDescription, Any]]:
        for action in reversed(draw_actions):
            output_ids = getattr(action, "outputs", None) or ()
            for rid in output_ids:
                rid_text = utils.normalize_resource_id(rid)
                if rid_text and rid_text in self._texture_ids:
                    return action, rid
        return None

    def _export_capture_thumbnail_png(self, image_path: Path, max_size: int = 2048) -> bool:
        if self.cap is None:
            return False
        try:
            thumb = self.cap.GetThumbnail(rd.FileType.PNG, int(max_size))
        except Exception:
            return False

        data = bytes(getattr(thumb, "data", b"") or b"")
        if not data:
            return False

        image_path.write_bytes(data)
        width = int(getattr(thumb, "width", 0) or 0)
        height = int(getattr(thumb, "height", 0) or 0)
        self._log(f"final frame exported from thumbnail: {width}x{height}, path={image_path.name}")
        return True

    def _export_final_frame_png(self, draw_actions: List[rd.ActionDescription]) -> Optional[str]:
        if (
            self.controller is None
            or self.material_module.output_dir is None
            or self.material_module.output_base_dir is None
        ):
            return None

        image_path = self.material_module.output_base_dir / "preview.png"
        if image_path.exists() and image_path.is_file():
            image_path.unlink()

        # Prefer embedded capture thumbnail. It's faster and stable across replay state.
        if self._export_capture_thumbnail_png(image_path):
            rel_path = image_path.relative_to(self.material_module.output_base_dir).as_posix()
            return rel_path

        self._ensure_texture_catalog()
        selected = self._select_final_frame_output(draw_actions)
        if selected is None:
            self._log("final frame export skipped: no thumbnail and no color output resource found")
            return None

        action, resource_id = selected
        rid_text = utils.normalize_resource_id(resource_id)
        if not rid_text:
            self._log("final frame export skipped: invalid output resource id")
            return None

        try:
            self.controller.SetFrameEvent(action.eventId, True)
            save_data = rd.TextureSave()
            save_data.resourceId = resource_id
            save_data.destType = rd.FileType.PNG
            save_data.mip = 0

            sample = rd.TextureSampleMapping()
            sample.mapToArray = False
            sample.sampleIndex = rd.TextureSampleMapping.ResolveSamples
            save_data.sample = sample

            slice_mapping = rd.TextureSliceMapping()
            slice_mapping.sliceIndex = 0
            slice_mapping.slicesAsGrid = False
            slice_mapping.cubeCruciform = False
            slice_mapping.sliceGridWidth = 0
            save_data.slice = slice_mapping

            result = self.controller.SaveTexture(save_data, str(image_path))
            ok = bool(result)
            try:
                ok = bool(result.OK())
            except Exception:
                pass

            if not ok:
                msg = ""
                try:
                    msg = result.Message() or ""
                except Exception:
                    pass
                if image_path.exists():
                    image_path.unlink(missing_ok=True)
                self._log(f"final frame export failed: event_id={action.eventId}, resource_id={rid_text}, error={msg}")
                return None
        except Exception as exc:
            if image_path.exists():
                image_path.unlink(missing_ok=True)
            self._log(f"final frame export failed: event_id={action.eventId}, resource_id={rid_text}, error={exc}")
            return None

        rel_path = image_path.relative_to(self.material_module.output_base_dir).as_posix()
        self._log(f"final frame exported: event_id={action.eventId}, resource_id={rid_text}, path={rel_path}")
        return rel_path

    def _parse_revision1(
        self,
        include_source: bool = False,
    ) -> Dict[str, Any]:
        if self.controller is None:
            raise RuntimeError("Parser is not loaded")

        material_map: Dict[str, Dict[str, Any]] = {}
        shader_registry: Dict[str, Dict[str, Any]] = {}
        shader_key_set: Set[str] = set()
        pass_map: Dict[str, Dict[str, Any]] = {}
        used_texture_ids: Set[str] = set()
        parse_start = time.perf_counter()

        pipeline_type = "Unknown"
        try:
            api_props = self.controller.GetAPIProperties()
            pipeline_type = utils.enum_name(getattr(api_props, "pipelineType", None)) or "Unknown"
        except Exception:
            pass

        collect_textures = self.texture_module.output_dir is not None
        shader_stages = self.shader_module.shader_stages() if collect_textures else []
        all_actions = rdc_utils.list_all_actions(self.controller)
        draw_actions = [action for action in all_actions if rdc_utils.is_draw_or_dispatch(action)]
        self._log(
            "scan start: "
            f"total_actions={len(all_actions)}, draw_or_dispatch_actions={len(draw_actions)}, "
            f"include_source={include_source}, "
            f"collect_textures={collect_textures}, "
            f"export_texture_images={self.texture_module.export_texture_images}"
        )

        for index, action in enumerate(draw_actions, start=1):
            action_start = time.perf_counter()

            self.controller.SetFrameEvent(action.eventId, True)
            state = self.controller.GetPipelineState()

            shader_items = self.shader_module.extract_shaders(state, include_source=include_source)
            shader_keys = sorted(set(item["shader_key"] for item in shader_items))
            shader_key_set.update(shader_keys)
            stage_shader_map = self._build_stage_shader_map(shader_items)

            texture_ids: List[str] = []
            if collect_textures:
                texture_ids = self.texture_module.extract_texture_ids(state, shader_stages)
                used_texture_ids.update(texture_ids)

            pass_features = self.pass_module.extract_pass_features(action, state, pipeline_type)
            pass_key = str(pass_features.get("pass_key", ""))
            marker_context = PassModule.extract_marker_context(pass_features.get("marker_path", ""))
            pass_channel = str(pass_features.get("pass_channel", "") or marker_context.get("pass_channel", ""))
            material_instance_name = marker_context.get("material_instance_name", "")
            mesh_name = marker_context.get("mesh_name", "")
            marker_path = str(pass_features.get("marker_path", "") or "")
            if material_instance_name:
                material_base_key = self.material_module.build_material_instance_key(material_instance_name)
            else:
                material_base_key = self.material_module.build_material_stable_key(
                    shader_keys=shader_keys,
                    material_instance_name=material_instance_name,
                    mesh_name=mesh_name,
                    pass_channel=pass_channel,
                )
            shader_set_key = self.material_module.build_shader_set_key(stage_shader_map)

            material_entry = material_map.get(material_base_key)
            if material_entry is None:
                material_entry = {
                    "material_base_key": material_base_key,
                    "_shader_detail_map": {},
                    "_shader_set_map": {},
                    "_pass_channel_set": set(),
                    "_material_instance_name_set": set(),
                    "_mesh_name_set": set(),
                    "_usage_count": 0,
                }
                material_map[material_base_key] = material_entry

            material_entry["_usage_count"] += 1
            if pass_channel:
                material_entry["_pass_channel_set"].add(pass_channel)
            if material_instance_name:
                material_entry["_material_instance_name_set"].add(material_instance_name)
            if mesh_name:
                material_entry["_mesh_name_set"].add(mesh_name)
            if shader_set_key and shader_set_key not in material_entry["_shader_set_map"]:
                material_entry["_shader_set_map"][shader_set_key] = dict(stage_shader_map)

            shader_detail_map = material_entry.get("_shader_detail_map", {})
            for shader_item in shader_items:
                shader_key = str(shader_item.get("shader_key", "") or "")
                if not shader_key:
                    continue

                shader_detail = shader_detail_map.get(shader_key)
                if shader_detail is None:
                    shader_detail = {
                        "shader_key": shader_key,
                        "stage": str(shader_item.get("stage", "") or ""),
                        "_source_path_set": set(),
                    }
                    shader_detail_map[shader_key] = shader_detail

                for source_file in shader_item.get("source_files", []) or []:
                    if not isinstance(source_file, dict):
                        continue
                    source_path = str(source_file.get("source_path", "") or "")
                    if source_path:
                        shader_detail["_source_path_set"].add(source_path)

            pass_entry = pass_map.get(pass_key)
            if pass_entry is None:
                pass_entry = {
                    "pass_key": pass_key,
                    "pipeline_type": str(pass_features.get("pipeline_type", "Unknown") or "Unknown"),
                    "marker_path": str(pass_features.get("marker_path", "root") or "root"),
                    "pass_channel": pass_channel,
                    "_material_key_set": set(),
                }
                pass_map[pass_key] = pass_entry

            pass_entry["_material_key_set"].add(material_base_key)

            if collect_textures:
                for texture_id in texture_ids:
                    self.texture_module.ensure_texture_export(texture_id)

            if self.shader_module.output_dir is not None:
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
                    f"shaders={len(shader_key_set)}, used_textures={len(used_texture_ids)}, "
                    f"elapsed={time.perf_counter() - parse_start:.2f}s"
                )

        self._log(f"scan done: elapsed={time.perf_counter() - parse_start:.2f}s")
        final_frame_image = self._export_final_frame_png(draw_actions)

        material_rows: List[Tuple[str, Dict[str, Any], int]] = []
        material_summary_rows: List[Dict[str, Any]] = []
        for material_entry in material_map.values():
            material_key = str(material_entry.get("material_base_key", "") or "")
            shader_rows: List[Dict[str, Any]] = []
            for shader_detail in material_entry.get("_shader_detail_map", {}).values():
                row = {
                    "shader_key": str(shader_detail.get("shader_key", "") or ""),
                    "stage": str(shader_detail.get("stage", "") or ""),
                    "source_paths": sorted(shader_detail.get("_source_path_set", set())),
                }
                shader_rows.append(row)
            shader_rows.sort(key=lambda item: (item.get("stage", ""), item.get("shader_key", "")))

            shader_sets = sorted(
                [dict(item) for item in material_entry.get("_shader_set_map", {}).values()],
                key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
            )
            material_instance_names = sorted(material_entry.get("_material_instance_name_set", set()))
            mesh_names = sorted(material_entry.get("_mesh_name_set", set()))
            pass_channels = sorted(material_entry.get("_pass_channel_set", set()))
            material_instance_name = material_instance_names[0] if material_instance_names else ""
            content_signature = self.material_module.build_content_signature(
                mesh_names=mesh_names,
                pass_channels=pass_channels,
                shader_sets=shader_sets,
            )

            material_payload = {
                "material_key": material_key,
                "material_instance_name": material_instance_name,
                "material_instance_names": material_instance_names,
                "mesh_names": mesh_names,
                "pass_channels": pass_channels,
                "shader_sets": shader_sets,
                "content_signature": content_signature,
                "shaders": shader_rows,
            }
            material_rows.append((material_key, material_payload, int(material_entry.get("_usage_count", 0) or 0)))
            material_summary_rows.append(
                {
                    "material_key": material_key,
                    "material_instance_name": material_instance_name,
                    "mesh_names": mesh_names,
                    "pass_channels": pass_channels,
                    "shader_sets": shader_sets,
                    "content_signature": content_signature,
                }
            )

        material_rows.sort(key=lambda item: item[2], reverse=True)
        material_summary_rows.sort(key=lambda item: item.get("material_key", ""))
        material_pairs: List[Tuple[str, str]] = []
        material_path_map: Dict[str, str] = {}
        material_persist_start = time.perf_counter()
        self._log(f"persist materials start: count={len(material_rows)}")
        for material_key, material_payload, _usage in material_rows:
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
            summary_path = self._write_json_file(
                self.material_module.output_dir,
                material_summary_rows,
                file_name="frame_material_summaries.json",
            )
            if index_path:
                artifacts["materials"] = {
                    "index": index_path,
                    "count": len(material_index_entries),
                }
                if summary_path:
                    artifacts["materials"]["summaries"] = summary_path

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
            pass_rows = sorted(
                pass_map.values(),
                key=lambda x: (len(x.get("_material_key_set", set())), x.get("pass_key", "")),
                reverse=True,
            )
            pass_pairs: List[Tuple[str, str]] = []
            pass_stage_start = time.perf_counter()
            self._log(f"persist passes start: count={len(pass_rows)}")
            for index, pass_entry in enumerate(pass_rows, start=1):
                pass_key = str(pass_entry.get("pass_key", ""))
                material_paths = []
                for mat_key in sorted(pass_entry.get("_material_key_set", set())):
                    material_path = material_path_map.get(mat_key)
                    if material_path:
                        material_paths.append({"material_path": material_path})
                pass_payload = {
                    "pass_key": pass_key,
                    "pipeline_type": str(pass_entry.get("pipeline_type", "Unknown") or "Unknown"),
                    "marker_path": str(pass_entry.get("marker_path", "root") or "root"),
                    "pass_channel": str(pass_entry.get("pass_channel", "") or ""),
                    "material": material_paths,
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

        if final_frame_image is not None:
            artifacts["preview_image"] = final_frame_image

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
        export_texture_images: bool = False,
    ) -> Dict[str, Any]:
        normalized = str(schema or "1").strip().lower()
        self.texture_module.set_export_texture_images(bool(export_texture_images))
        wants_texture_output = bool(texture_output_dir)

        if normalized in {"1", "v1", "rev1", "first"}:
            if wants_texture_output:
                self._ensure_texture_catalog()
            self.shader_module.configure_shader_output_dir(shader_output_dir)
            self.shader_module.configure_source_output_dir(source_output_dir if include_source else None)
            self.material_module.configure_output_dir(material_output_dir)
            self.texture_module.configure_output_dir(texture_output_dir)
            self.pass_module.configure_output_dir(pass_output_dir)
        else:
            self._ensure_texture_catalog()
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
    export_texture_images: bool = False,
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
