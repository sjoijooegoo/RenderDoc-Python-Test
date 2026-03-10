from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import renderdoc as rd

from .. import utils
from .io_utils import relative_artifact_path, safe_file_part


class ShaderModule:
    def __init__(self) -> None:
        self.resource_names: Dict[str, str] = {}
        self.output_dir: Optional[Path] = None
        self.output_base_dir: Optional[Path] = None
        self.source_output_dir: Optional[Path] = None
        self.source_output_base_dir: Optional[Path] = None
        self.shared_source_dir: Optional[Path] = None
        self._source_content_map: Dict[str, Path] = {}

    def set_resource_names(self, resource_names: Dict[str, str]) -> None:
        self.resource_names = resource_names

    def configure_shader_output_dir(self, shader_output_dir: Optional[str]) -> None:
        self.output_dir = None
        self.output_base_dir = None
        if not shader_output_dir:
            return

        shader_dir = Path(shader_output_dir).resolve()
        shader_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir = shader_dir
        self.output_base_dir = shader_dir.parent

    def configure_source_output_dir(self, source_output_dir: Optional[str]) -> None:
        self.source_output_dir = None
        self.source_output_base_dir = None
        self.shared_source_dir = None
        self._source_content_map = {}
        if not source_output_dir:
            return

        source_dir = Path(source_output_dir).resolve()
        source_dir.mkdir(parents=True, exist_ok=True)
        self.source_output_dir = source_dir
        self.source_output_base_dir = source_dir.parent
        shared_source_dir = source_dir / "_shared_sources"
        shared_source_dir.mkdir(parents=True, exist_ok=True)
        self.shared_source_dir = shared_source_dir

    def _shader_dir_for_key(self, shader_key: str) -> Optional[Path]:
        if self.output_dir is None:
            return None
        return self.output_dir / safe_file_part(shader_key.replace(":", "_"))

    def shader_json_path(self, shader_key: str) -> Optional[str]:
        shader_dir = self._shader_dir_for_key(shader_key)
        if shader_dir is None:
            return None
        return relative_artifact_path(shader_dir / "rdc_shader.json", self.output_base_dir)

    def persist_shader_record(self, shader_payload: Dict[str, Any]) -> Optional[str]:
        shader_key = str(shader_payload.get("shader_key", "") or "")
        shader_dir = self._shader_dir_for_key(shader_key)
        if shader_dir is None:
            return None

        shader_dir.mkdir(parents=True, exist_ok=True)
        target_path = shader_dir / "rdc_shader.json"
        target_path.write_text(json.dumps(shader_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return relative_artifact_path(target_path, self.output_base_dir)

    def shader_stages(self) -> List[rd.ShaderStage]:
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

    def _describe_resource_id(self, resource_id: rd.ResourceId) -> Dict[str, str]:
        rid = utils.normalize_resource_id(resource_id)
        if not rid:
            return {"id": "", "name": ""}
        return {"id": rid, "name": self.resource_names.get(rid, "")}

    def _collect_shader_source_files(
        self, shader: rd.ShaderReflection, include_source: bool
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        files: List[Dict[str, Any]] = []
        merged_sources: List[str] = []

        debug_info = getattr(shader, "debugInfo", None)
        debug_files = getattr(debug_info, "files", None)
        if not debug_files:
            return files, merged_sources

        for src in debug_files:
            content = getattr(src, "contents", "") or ""
            if content:
                merged_sources.append(content)

            item = {
                "_line_count": utils.count_lines(content),
                "_debug_filename": getattr(src, "filename", "") or "",
            }
            if include_source:
                item["content"] = content
            files.append(item)

        return files, merged_sources

    def _persist_shared_source(self, content: str, preferred_filename: str) -> Optional[Path]:
        if self.shared_source_dir is None:
            return None

        source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        cached_path = self._source_content_map.get(source_hash)
        if cached_path is not None:
            return cached_path

        base_name = Path(preferred_filename).name if preferred_filename else ""
        suffix = Path(base_name).suffix
        if not suffix:
            suffix = ".txt"
        file_name = f"src_{source_hash[:16]}{suffix}"
        file_name = safe_file_part(file_name)
        target_path = self.shared_source_dir / file_name
        if not target_path.exists():
            target_path.write_text(content, encoding="utf-8")
        self._source_content_map[source_hash] = target_path
        return target_path

    def _persist_source_files(self, _shader_key: str, source_files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if self.source_output_dir is None:
            return source_files

        persisted: List[Dict[str, Any]] = []
        for src in source_files:
            item = dict(src)
            content = str(item.pop("content", "") or "")
            debug_filename = str(item.pop("_debug_filename", "") or "")
            target_path = self._persist_shared_source(content, debug_filename)
            if target_path is not None:
                item["source_path"] = relative_artifact_path(target_path, self.source_output_base_dir)
            persisted.append(item)

        return persisted

    @staticmethod
    def _sanitize_source_files(source_files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        sanitized: List[Dict[str, Any]] = []
        for src in source_files:
            item: Dict[str, Any] = {}
            source_path = str(dict(src).get("source_path", "") or "")
            if source_path:
                item["source_path"] = source_path
            if item:
                sanitized.append(item)
        return sanitized

    def _collect_constant_layout_tokens(self, shader: rd.ShaderReflection, stage_name: str) -> List[str]:
        tokens: List[str] = []
        try:
            for block in getattr(shader, "constantBlocks", None) or []:
                name = getattr(block, "name", "") or ""
                byte_size = int(getattr(block, "byteSize", 0) or 0)
                bind_set = int(getattr(block, "fixedBindSetOrSpace", -1) or -1)
                bind_number = int(getattr(block, "fixedBindNumber", -1) or -1)
                var_count = len(getattr(block, "variables", None) or [])
                tokens.append(f"{stage_name}:{name}:{byte_size}:{bind_set}:{bind_number}:{var_count}")
        except Exception:
            return tokens

        return tokens

    def extract_shaders(self, state: rd.PipeState, include_source: bool) -> List[Dict[str, Any]]:
        shader_items: List[Dict[str, Any]] = []
        for stage in self.shader_stages():
            shader = state.GetShaderReflection(stage)
            if shader is None:
                continue

            stage_name = utils.enum_name(stage)
            source_files, merged_sources = self._collect_shader_source_files(shader, include_source)
            source_md5 = ""
            if merged_sources:
                source_md5 = hashlib.md5("\n".join(merged_sources).encode("utf-8")).hexdigest()

            info: Dict[str, Any] = {
                "stage": stage_name,
                "entry_point": state.GetShaderEntryPoint(stage) or getattr(shader, "entryPoint", "") or "",
                "resource": self._describe_resource_id(shader.resourceId),
                "source_files": source_files,
                "source_file_count": len(source_files),
                "source_line_count": sum(int(x.get("_line_count", 0)) for x in source_files),
                "source_md5": source_md5,
                "constant_layout_tokens": self._collect_constant_layout_tokens(shader, stage_name),
            }
            info["shader_key"] = utils.make_shader_key(info)
            if include_source:
                info["source_files"] = self._persist_source_files(info["shader_key"], info["source_files"])
            info["source_files"] = self._sanitize_source_files(info["source_files"])
            shader_items.append(info)

        return shader_items

    @staticmethod
    def extract_constant_layout_tokens_from_shaders(shader_items: List[Dict[str, Any]]) -> List[str]:
        tokens: List[str] = []
        for item in shader_items:
            tokens.extend(item.get("constant_layout_tokens", []) or [])
        return utils.stable_unique_sorted(tokens)

    @staticmethod
    def register_shader(shader_registry: Dict[str, Dict[str, Any]], shader_item: Dict[str, Any]) -> None:
        shader_key = shader_item["shader_key"]
        entry = shader_registry.get(shader_key)
        if entry is None:
            entry = {
                "shader_key": shader_key,
                "stage": shader_item.get("stage", ""),
                "entry_point": shader_item.get("entry_point", ""),
                "source_line_count": int(shader_item.get("source_line_count", 0)),
                "usage_count": 0,
            }

            source_files = shader_item.get("source_files") or []
            if source_files:
                entry["source_files"] = source_files

            shader_registry[shader_key] = entry

        entry["usage_count"] += 1
