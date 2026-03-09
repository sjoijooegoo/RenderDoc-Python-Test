from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

import renderdoc as rd

from .capture_loader import load_capture
from . import rdc_utils
from . import utils


class MaterialShaderParser:
    """Parse one .rdc file and extract material/shader-focused data."""

    def __init__(self, filename: str):
        self.filename = filename
        self.cap: Optional[rd.CaptureFile] = None
        self.controller: Optional[rd.ReplayController] = None
        self._resource_names: Dict[str, str] = {}
        self._texture_ids: set[str] = set()

    def load(self) -> None:
        self.cap, self.controller = load_capture(self.filename)
        self._resource_names = self._build_resource_name_map()
        self._texture_ids = self._build_texture_id_set()

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

    def __enter__(self) -> "MaterialShaderParser":
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

    def _build_texture_id_set(self) -> set[str]:
        if self.controller is None:
            return set()

        tex_ids: set[str] = set()
        try:
            for tex in self.controller.GetTextures():
                tex_ids.add(str(tex.resourceId))
        except Exception:
            return tex_ids

        return tex_ids

    def _describe_resource_id(self, resource_id: rd.ResourceId) -> Dict[str, str]:
        if resource_id is None or resource_id == rd.ResourceId.Null():
            return {"id": "", "name": ""}
        rid = str(resource_id)
        return {"id": rid, "name": self._resource_names.get(rid, "")}

    def _shader_stages(self) -> List[rd.ShaderStage]:
        stages = [
            rd.ShaderStage.Vertex,
            rd.ShaderStage.Hull,
            rd.ShaderStage.Domain,
            rd.ShaderStage.Geometry,
            rd.ShaderStage.Pixel,
            rd.ShaderStage.Compute,
        ]

        optional_names = ["Task", "Mesh", "RayGen"]
        for name in optional_names:
            if hasattr(rd.ShaderStage, name):
                stages.append(getattr(rd.ShaderStage, name))

        return stages

    def _collect_shader_source_files(self, shader: rd.ShaderReflection, include_source: bool) -> List[Dict[str, Any]]:
        files: List[Dict[str, Any]] = []
        debug_info = getattr(shader, "debugInfo", None)
        debug_files = getattr(debug_info, "files", None)
        if not debug_files:
            return files

        for src in debug_files:
            content = getattr(src, "contents", "") or ""
            item = {
                "filename": getattr(src, "filename", "") or "",
                "line_count": utils.count_lines(content),
            }
            if include_source:
                item["content"] = content
            files.append(item)

        return files

    def _extract_shaders(self, state: rd.PipeState, include_source: bool) -> List[Dict[str, Any]]:
        shader_items: List[Dict[str, Any]] = []

        for stage in self._shader_stages():
            shader = state.GetShaderReflection(stage)
            if shader is None:
                continue

            source_files = self._collect_shader_source_files(shader, include_source)
            merged_sources: List[str] = []
            for src in source_files:
                content = src.get("content") or ""
                if content:
                    merged_sources.append(content)

            source_md5 = ""
            if merged_sources:
                source_md5 = hashlib.md5("\n".join(merged_sources).encode("utf-8")).hexdigest()

            info: Dict[str, Any] = {
                "stage": utils.enum_name(stage),
                "entry_point": state.GetShaderEntryPoint(stage) or getattr(shader, "entryPoint", "") or "",
                "resource": self._describe_resource_id(shader.resourceId),
                "source_files": source_files,
                "source_file_count": len(source_files),
                "source_line_count": sum(int(x.get("line_count", 0)) for x in source_files),
                "source_md5": source_md5,
            }
            info["shader_key"] = utils.make_shader_key(info)
            shader_items.append(info)

        return shader_items

    def _collect_texture_ids_from_used_descriptors(self, used_descriptors) -> set[str]:
        tex_ids: set[str] = set()

        for used in used_descriptors or []:
            descriptor = getattr(used, "descriptor", None)
            if descriptor is None:
                continue

            resource_candidates = [
                getattr(descriptor, "resource", None),
                getattr(descriptor, "view", None),
            ]
            for candidate in resource_candidates:
                if candidate is None or candidate == rd.ResourceId.Null():
                    continue
                rid = str(candidate)
                if rid in self._texture_ids:
                    tex_ids.add(rid)

        return tex_ids

    def _extract_texture_ids(self, state: rd.PipeState) -> List[str]:
        tex_ids: set[str] = set()

        for stage in self._shader_stages():
            try:
                tex_ids |= self._collect_texture_ids_from_used_descriptors(
                    state.GetReadOnlyResources(stage, True)
                )
                tex_ids |= self._collect_texture_ids_from_used_descriptors(
                    state.GetReadWriteResources(stage, True)
                )
            except Exception:
                continue

        return sorted(tex_ids)

    def parse(self, include_source: bool = False) -> Dict[str, Any]:
        if self.controller is None:
            raise RuntimeError("Parser is not loaded")

        shader_registry: Dict[str, Dict[str, Any]] = {}
        material_map: Dict[str, Dict[str, Any]] = {}

        stage_line_counts_by_usage: Dict[str, int] = {}
        total_shader_lines_by_usage = 0

        for action in rdc_utils.list_all_actions(self.controller):
            if not rdc_utils.is_draw_or_dispatch(action):
                continue

            self.controller.SetFrameEvent(action.eventId, True)
            state = self.controller.GetPipelineState()

            shaders = self._extract_shaders(state, include_source)
            texture_ids = self._extract_texture_ids(state)
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

        return {
            "capture_file": self.filename,
            "summary": summary,
            "materials": materials,
            "shaders": shaders,
        }


def parse_capture_material_shader(filename: str, include_source: bool = False) -> Dict[str, Any]:
    with MaterialShaderParser(filename) as parser:
        return parser.parse(include_source=include_source)
