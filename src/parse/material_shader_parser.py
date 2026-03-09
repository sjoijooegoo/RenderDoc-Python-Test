from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import renderdoc as rd

from . import rdc_utils
from . import utils
from .capture_loader import load_capture


class MaterialShaderParser:
    """Parse one .rdc file and extract material/shader-focused data."""

    def __init__(self, filename: str):
        self.filename = filename
        self.cap: Optional[rd.CaptureFile] = None
        self.controller: Optional[rd.ReplayController] = None
        self._resource_names: Dict[str, str] = {}
        self._texture_ids: Set[str] = set()
        self._texture_desc_map: Dict[str, Any] = {}
        self._source_output_dir: Optional[Path] = None
        self._source_output_base_dir: Optional[Path] = None
        self._material_output_dir: Optional[Path] = None
        self._material_output_base_dir: Optional[Path] = None
        self._texture_output_dir: Optional[Path] = None
        self._texture_output_base_dir: Optional[Path] = None
        self._shader_output_dir: Optional[Path] = None
        self._shader_output_base_dir: Optional[Path] = None
        self._texture_export_map: Dict[str, Dict[str, Any]] = {}
        self._export_texture_images: bool = True

    def load(self) -> None:
        self.cap, self.controller = load_capture(self.filename)
        self._resource_names = self._build_resource_name_map()
        self._texture_ids = self._build_texture_id_set()
        self._texture_desc_map = self._build_texture_desc_map()

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

    def _build_texture_id_set(self) -> Set[str]:
        if self.controller is None:
            return set()

        tex_ids: Set[str] = set()
        try:
            for tex in self.controller.GetTextures():
                rid = utils.normalize_resource_id(tex.resourceId)
                if rid:
                    tex_ids.add(rid)
        except Exception:
            return tex_ids

        return tex_ids

    def _build_texture_desc_map(self) -> Dict[str, Any]:
        if self.controller is None:
            return {}

        texture_map: Dict[str, Any] = {}
        try:
            for tex in self.controller.GetTextures():
                rid = utils.normalize_resource_id(getattr(tex, "resourceId", None))
                if rid:
                    texture_map[rid] = tex
        except Exception:
            return texture_map

        return texture_map

    def _describe_resource_id(self, resource_id: rd.ResourceId) -> Dict[str, str]:
        rid = utils.normalize_resource_id(resource_id)
        if not rid:
            return {"id": "", "name": ""}
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
                "filename": getattr(src, "filename", "") or "",
                "line_count": utils.count_lines(content),
            }
            if include_source:
                item["content"] = content
            files.append(item)

        return files, merged_sources

    def _configure_source_output_dir(self, source_output_dir: Optional[str]) -> None:
        self._source_output_dir = None
        self._source_output_base_dir = None
        if not source_output_dir:
            return

        source_dir = Path(source_output_dir).resolve()
        source_dir.mkdir(parents=True, exist_ok=True)
        self._source_output_dir = source_dir
        self._source_output_base_dir = source_dir.parent

    def _configure_material_output_dir(self, material_output_dir: Optional[str]) -> None:
        self._material_output_dir = None
        self._material_output_base_dir = None
        if not material_output_dir:
            return

        material_dir = Path(material_output_dir).resolve()
        material_dir.mkdir(parents=True, exist_ok=True)
        self._material_output_dir = material_dir
        self._material_output_base_dir = material_dir.parent

    def _configure_texture_output_dir(self, texture_output_dir: Optional[str]) -> None:
        self._texture_output_dir = None
        self._texture_output_base_dir = None
        self._texture_export_map = {}
        if not texture_output_dir:
            return

        texture_dir = Path(texture_output_dir).resolve()
        texture_dir.mkdir(parents=True, exist_ok=True)
        self._texture_output_dir = texture_dir
        self._texture_output_base_dir = texture_dir.parent

    def _configure_shader_output_dir(self, shader_output_dir: Optional[str]) -> None:
        self._shader_output_dir = None
        self._shader_output_base_dir = None
        if not shader_output_dir:
            return

        shader_dir = Path(shader_output_dir).resolve()
        shader_dir.mkdir(parents=True, exist_ok=True)
        self._shader_output_dir = shader_dir
        self._shader_output_base_dir = shader_dir.parent

    def _safe_file_part(self, text: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", text.strip())
        safe = safe.strip("._")
        return safe or "source"

    def _relative_artifact_path(self, file_path: Path, base_dir: Optional[Path]) -> str:
        if base_dir is None:
            return str(file_path)
        return file_path.relative_to(base_dir).as_posix()

    def _material_dir_for_key(self, material_base_key: str) -> Optional[Path]:
        if self._material_output_dir is None:
            return None
        return self._material_output_dir / self._safe_file_part(material_base_key.replace(":", "_"))

    def _texture_dir_for_id(self, texture_id: str) -> Optional[Path]:
        if self._texture_output_dir is None:
            return None
        return self._texture_output_dir / self._safe_file_part(texture_id.replace(":", "_"))

    def _shader_dir_for_key(self, shader_key: str) -> Optional[Path]:
        if self._shader_output_dir is None:
            return None
        return self._shader_output_dir / self._safe_file_part(shader_key.replace(":", "_"))

    def _texture_json_path(self, texture_id: str) -> Optional[str]:
        texture_dir = self._texture_dir_for_id(texture_id)
        if texture_dir is None:
            return None
        return self._relative_artifact_path(texture_dir / "rdc_texture.json", self._texture_output_base_dir)

    def _shader_json_path(self, shader_key: str) -> Optional[str]:
        shader_dir = self._shader_dir_for_key(shader_key)
        if shader_dir is None:
            return None
        return self._relative_artifact_path(shader_dir / "rdc_shader.json", self._shader_output_base_dir)

    def _sha256_file(self, file_path: Path) -> str:
        digest = hashlib.sha256()
        with file_path.open("rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def _build_index_entries(
        self, pairs: List[Tuple[str, str]], base_dir: Optional[Path]
    ) -> List[Dict[str, str]]:
        entries: List[Dict[str, str]] = []
        for item_id, rel_path in pairs:
            entry: Dict[str, str] = {"id": item_id, "path": rel_path}
            if base_dir is not None:
                abs_path = (base_dir / rel_path).resolve()
                if abs_path.exists() and abs_path.is_file():
                    entry["sha256"] = self._sha256_file(abs_path)
            entries.append(entry)
        return entries

    def _write_index_file(
        self, dir_path: Optional[Path], items: List[Dict[str, str]], file_name: str = "index.json"
    ) -> Optional[str]:
        if dir_path is None:
            return None
        target = dir_path / file_name
        target.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._relative_artifact_path(target, dir_path.parent)

    def _capture_id(self) -> str:
        try:
            capture_path = Path(self.filename).resolve()
            stat = capture_path.stat()
            token = f"{capture_path.name}|{stat.st_size}|{int(stat.st_mtime_ns)}"
        except Exception:
            token = Path(self.filename).name
        return f"cap:{hashlib.md5(token.encode('utf-8')).hexdigest()}"

    def _compute_texture_compare_key(self, texture_id: str, record: Dict[str, Any]) -> str:
        name = str(record.get("resource_name", "") or "")
        fmt = str(record.get("format", "") or "")
        width = int(record.get("width", 0) or 0)
        height = int(record.get("height", 0) or 0)
        mips = int(record.get("mips", 0) or 0)
        array_size = int(record.get("array_size", 0) or 0)
        token = f"{name}|{fmt}|{width}|{height}|{mips}|{array_size}"
        if not token.strip("|"):
            token = texture_id
        return f"texcmp:{hashlib.md5(token.encode('utf-8')).hexdigest()}"

    def _texture_compare_key(self, texture_id: str) -> str:
        record = self._texture_export_map.get(texture_id) or self._ensure_texture_export(texture_id)
        return self._compute_texture_compare_key(texture_id, record)

    def _persist_source_files(self, shader_key: str, source_files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if self._source_output_dir is None:
            return source_files

        shader_dir = self._shader_dir_for_key(shader_key)
        if shader_dir is None:
            shader_dir = self._source_output_dir / self._safe_file_part(shader_key.replace(":", "_"))
        shader_dir.mkdir(parents=True, exist_ok=True)

        persisted: List[Dict[str, Any]] = []
        used_names: Set[str] = set()
        for index, src in enumerate(source_files, start=1):
            item = dict(src)
            content = str(item.pop("content", "") or "")

            original_name = str(item.get("filename", "") or "")
            base_name = Path(original_name).name if original_name else ""
            safe_name = self._safe_file_part(base_name or f"source_{index:02d}.txt")
            candidate = Path(safe_name)
            stem = candidate.stem or f"source_{index:02d}"
            suffix = candidate.suffix
            file_name = f"{stem}{suffix}"
            seq = 2
            while file_name.lower() in used_names or (shader_dir / file_name).exists():
                file_name = f"{stem}_{seq:02d}{suffix}"
                seq += 1
            used_names.add(file_name.lower())
            target_path = shader_dir / file_name
            target_path.write_text(content, encoding="utf-8")

            item["source_path"] = self._relative_artifact_path(target_path, self._source_output_base_dir)

            persisted.append(item)

        return persisted

    def _ensure_texture_export(self, texture_id: str) -> Dict[str, Any]:
        cached = self._texture_export_map.get(texture_id)
        if cached and cached.get("image_path"):
            return cached

        record: Dict[str, Any] = dict(cached or {})
        record.setdefault("resource_id", texture_id)
        record.setdefault("resource_name", self._resource_names.get(texture_id, ""))

        tex_desc = self._texture_desc_map.get(texture_id)
        if tex_desc is not None:
            format_name = ""
            fmt = getattr(tex_desc, "format", None)
            if fmt is not None:
                try:
                    format_name = fmt.Name() or ""
                except Exception:
                    format_name = str(fmt)
            record["width"] = int(getattr(tex_desc, "width", 0) or 0)
            record["height"] = int(getattr(tex_desc, "height", 0) or 0)
            record["mips"] = int(getattr(tex_desc, "mips", 0) or 0)
            record["array_size"] = int(getattr(tex_desc, "arraysize", 0) or 0)
            record["format"] = format_name

        texture_dir = self._texture_dir_for_id(texture_id)
        if (
            texture_dir is None
            or self.controller is None
            or tex_desc is None
            or not self._export_texture_images
        ):
            self._texture_export_map[texture_id] = record
            return record

        texture_dir.mkdir(parents=True, exist_ok=True)
        target_path = texture_dir / "image.png"

        if target_path.exists():
            record["image_path"] = self._relative_artifact_path(target_path, self._texture_output_base_dir)
            try:
                record["image_sha256"] = self._sha256_file(target_path)
            except Exception:
                pass
            if "texture_compare_key" not in record:
                record["texture_compare_key"] = self._compute_texture_compare_key(texture_id, record)
            self._texture_export_map[texture_id] = record
            return record

        try:
            save_data = rd.TextureSave()
            save_data.resourceId = tex_desc.resourceId
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

            result = self.controller.SaveTexture(save_data, str(target_path))
            ok = bool(result)
            try:
                ok = bool(result.OK())
            except Exception:
                pass

            if ok:
                record["image_path"] = self._relative_artifact_path(target_path, self._texture_output_base_dir)
                try:
                    record["image_sha256"] = self._sha256_file(target_path)
                except Exception:
                    pass
            else:
                msg = ""
                try:
                    msg = result.Message()
                except Exception:
                    msg = ""
                if msg:
                    record["export_error"] = msg
        except Exception as exc:
            record["export_error"] = str(exc)

        if "texture_compare_key" not in record:
            record["texture_compare_key"] = self._compute_texture_compare_key(texture_id, record)

        self._texture_export_map[texture_id] = record
        return record

    def _build_texture_ref(self, texture_id: str) -> Dict[str, Any]:
        record = self._ensure_texture_export(texture_id)
        item = {
            "resource_id": record.get("resource_id", texture_id),
            "resource_name": record.get("resource_name", ""),
        }
        for key in ("width", "height", "mips", "array_size", "format", "image_path"):
            if key in record:
                item[key] = record[key]
        if "export_error" in record:
            item["export_error"] = record["export_error"]
        return item

    def _persist_texture_record(self, texture_id: str, record: Optional[Dict[str, Any]] = None) -> Optional[str]:
        if record is None:
            record = self._ensure_texture_export(texture_id)
        texture_dir = self._texture_dir_for_id(texture_id)
        if texture_dir is None:
            return None

        texture_dir.mkdir(parents=True, exist_ok=True)
        target_path = texture_dir / "rdc_texture.json"
        target_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._relative_artifact_path(target_path, self._texture_output_base_dir)

    def _persist_shader_record(self, shader_payload: Dict[str, Any]) -> Optional[str]:
        shader_key = str(shader_payload.get("shader_key", "") or "")
        shader_dir = self._shader_dir_for_key(shader_key)
        if shader_dir is None:
            return None

        shader_dir.mkdir(parents=True, exist_ok=True)
        target_path = shader_dir / "rdc_shader.json"
        target_path.write_text(json.dumps(shader_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._relative_artifact_path(target_path, self._shader_output_base_dir)

    def _persist_material_record(self, material_base_key: str, material_payload: Dict[str, Any]) -> Optional[str]:
        if self._material_output_dir is None:
            return None

        material_dir = self._material_dir_for_key(material_base_key)
        if material_dir is None:
            return None
        material_dir.mkdir(parents=True, exist_ok=True)
        target_path = material_dir / "rdc_material.json"
        target_path.write_text(json.dumps(material_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._relative_artifact_path(target_path, self._material_output_base_dir)

    def _collect_constant_layout_tokens(self, shader: rd.ShaderReflection, stage_name: str) -> List[str]:
        tokens: List[str] = []
        try:
            for block in getattr(shader, "constantBlocks", None) or []:
                name = getattr(block, "name", "") or ""
                byte_size = int(getattr(block, "byteSize", 0) or 0)
                bind_set = int(getattr(block, "fixedBindSetOrSpace", -1) or -1)
                bind_number = int(getattr(block, "fixedBindNumber", -1) or -1)
                var_count = len(getattr(block, "variables", None) or [])
                tokens.append(
                    f"{stage_name}:{name}:{byte_size}:{bind_set}:{bind_number}:{var_count}"
                )
        except Exception:
            return tokens

        return tokens

    def _extract_shaders(self, state: rd.PipeState, include_source: bool) -> List[Dict[str, Any]]:
        shader_items: List[Dict[str, Any]] = []

        for stage in self._shader_stages():
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
                "source_line_count": sum(int(x.get("line_count", 0)) for x in source_files),
                "source_md5": source_md5,
                "constant_layout_tokens": self._collect_constant_layout_tokens(shader, stage_name),
            }
            info["shader_key"] = utils.make_shader_key(info)
            if include_source:
                info["source_files"] = self._persist_source_files(info["shader_key"], info["source_files"])
            shader_items.append(info)

        return shader_items

    def _collect_resource_ids_from_used_descriptors(
        self, used_descriptors, texture_only: bool = False
    ) -> Set[str]:
        res_ids: Set[str] = set()

        for used in used_descriptors or []:
            descriptor = getattr(used, "descriptor", None)
            if descriptor is not None:
                for attr in ("resource", "view", "secondary"):
                    rid = utils.normalize_resource_id(getattr(descriptor, attr, None))
                    if rid and (not texture_only or rid in self._texture_ids):
                        res_ids.add(rid)

            sampler_desc = getattr(used, "sampler", None)
            if sampler_desc is not None:
                for attr in ("object", "ycbcrSampler"):
                    rid = utils.normalize_resource_id(getattr(sampler_desc, attr, None))
                    if rid and (not texture_only or rid in self._texture_ids):
                        res_ids.add(rid)

        return res_ids

    def _extract_texture_ids(self, state: rd.PipeState) -> List[str]:
        tex_ids: Set[str] = set()

        for stage in self._shader_stages():
            try:
                tex_ids |= self._collect_resource_ids_from_used_descriptors(
                    state.GetReadOnlyResources(stage, True), texture_only=True
                )
                tex_ids |= self._collect_resource_ids_from_used_descriptors(
                    state.GetReadWriteResources(stage, True), texture_only=True
                )
            except Exception:
                continue

        return sorted(tex_ids)

    def _extract_used_resource_ids(self, state: rd.PipeState) -> List[str]:
        resource_ids: Set[str] = set()

        for stage in self._shader_stages():
            try:
                resource_ids |= self._collect_resource_ids_from_used_descriptors(
                    state.GetReadOnlyResources(stage, True), texture_only=False
                )
                resource_ids |= self._collect_resource_ids_from_used_descriptors(
                    state.GetReadWriteResources(stage, True), texture_only=False
                )
            except Exception:
                continue

        return sorted(resource_ids)

    def _extract_sampler_ids(self, state: rd.PipeState) -> List[str]:
        sampler_ids: Set[str] = set()

        for stage in self._shader_stages():
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

    def _extract_constant_layout_tokens_from_shaders(self, shader_items: List[Dict[str, Any]]) -> List[str]:
        tokens: List[str] = []
        for item in shader_items:
            tokens.extend(item.get("constant_layout_tokens", []) or [])
        return utils.stable_unique_sorted(tokens)

    def _texture_signature_values(self, texture_ids: List[str]) -> List[str]:
        return [self._texture_compare_key(texture_id) for texture_id in sorted(set(texture_ids))]

    def _sampler_signature_values(self, sampler_ids: List[str]) -> List[str]:
        values: List[str] = []
        for sampler_id in sorted(set(sampler_ids)):
            sampler_name = str(self._resource_names.get(sampler_id, "") or "").strip()
            if sampler_name:
                values.append(f"name:{sampler_name}")
            else:
                # Fallback when sampler has no stable name in capture metadata.
                values.append(f"id:{sampler_id}")
        return values

    def _build_base_features(
        self, texture_ids: List[str], sampler_ids: List[str], constant_layout_tokens: List[str]
    ) -> Dict[str, str]:
        texture_values = self._texture_signature_values(texture_ids)
        sampler_values = self._sampler_signature_values(sampler_ids)
        return {
            "texture_signature": utils.make_signature(texture_values, "tex"),
            "sampler_signature": utils.make_signature(sampler_values, "smp"),
            "constant_layout_signature": utils.make_signature(constant_layout_tokens, "cbuf"),
        }

    def _build_material_base_key(self, base_features: Dict[str, str]) -> str:
        return utils.make_signature(
            [
                base_features.get("texture_signature", ""),
                base_features.get("sampler_signature", ""),
                base_features.get("constant_layout_signature", ""),
            ],
            "mat",
        )

    def _build_variant_key(self, shader_keys: List[str]) -> str:
        return utils.make_signature(shader_keys, "var")

    def _build_pass_key(self, action: rd.ActionDescription, state: rd.PipeState, pipeline_type: str) -> str:
        marker_path = ""
        if self.controller is not None:
            marker_path = rdc_utils.get_marker_path(action, self.controller)

        output_ids = [
            utils.normalize_resource_id(rid)
            for rid in (getattr(action, "outputs", None) or ())
        ]
        output_ids = [rid for rid in output_ids if rid]

        depth_out = utils.normalize_resource_id(getattr(action, "depthOut", None))

        pipeline_object = ""
        try:
            pipeline_object = utils.normalize_resource_id(state.GetGraphicsPipelineObject())
        except Exception:
            pipeline_object = ""
        if not pipeline_object:
            try:
                pipeline_object = utils.normalize_resource_id(state.GetComputePipelineObject())
            except Exception:
                pipeline_object = ""

        pass_tokens = [
            f"api:{pipeline_type or 'Unknown'}",
            f"marker:{marker_path or 'root'}",
            f"outputs:{','.join(sorted(output_ids)) or 'none'}",
            f"depth:{depth_out or 'none'}",
            f"pipeline:{pipeline_object or 'none'}",
        ]

        return utils.make_signature(pass_tokens, "pass")

    def _bound_buffer_token(self, bound_buffer: Any) -> str:
        if bound_buffer is None:
            return ""
        rid = utils.normalize_resource_id(getattr(bound_buffer, "resourceId", None))
        if not rid:
            return ""

        byte_offset = int(getattr(bound_buffer, "byteOffset", 0) or 0)
        byte_stride = int(getattr(bound_buffer, "byteStride", 0) or 0)
        byte_size = int(getattr(bound_buffer, "byteSize", 0) or 0)
        return f"{rid}:{byte_offset}:{byte_stride}:{byte_size}"

    def _build_mesh_key(self, action: rd.ActionDescription, state: rd.PipeState) -> str:
        mesh_tokens: List[str] = []

        try:
            mesh_tokens.append(f"topology:{utils.enum_name(state.GetPrimitiveTopology())}")
        except Exception:
            mesh_tokens.append("topology:Unknown")

        try:
            ib_token = self._bound_buffer_token(state.GetIBuffer())
            if ib_token:
                mesh_tokens.append(f"ib:{ib_token}")
        except Exception:
            pass

        try:
            vb_tokens = [self._bound_buffer_token(vb) for vb in state.GetVBuffers() or []]
            vb_tokens = [x for x in vb_tokens if x]
            if vb_tokens:
                mesh_tokens.append(f"vb:{'|'.join(sorted(vb_tokens))}")
        except Exception:
            pass

        try:
            attr_tokens = []
            for attr in state.GetVertexInputs() or []:
                if not getattr(attr, "used", False):
                    continue
                attr_tokens.append(
                    ":".join(
                        [
                            str(getattr(attr, "name", "") or ""),
                            str(getattr(attr, "vertexBuffer", -1)),
                            str(getattr(attr, "byteOffset", 0)),
                            str(getattr(attr, "format", "")),
                            str(int(bool(getattr(attr, "perInstance", False)))),
                            str(getattr(attr, "instanceRate", 0)),
                        ]
                    )
                )
            if attr_tokens:
                mesh_tokens.append(f"attr:{'|'.join(sorted(attr_tokens))}")
        except Exception:
            pass

        draw_tokens = [
            f"numIndices:{int(getattr(action, 'numIndices', 0) or 0)}",
            f"numInstances:{int(getattr(action, 'numInstances', 0) or 0)}",
            f"baseVertex:{int(getattr(action, 'baseVertex', 0) or 0)}",
            f"vertexOffset:{int(getattr(action, 'vertexOffset', 0) or 0)}",
            f"indexOffset:{int(getattr(action, 'indexOffset', 0) or 0)}",
            f"instanceOffset:{int(getattr(action, 'instanceOffset', 0) or 0)}",
            f"drawIndex:{int(getattr(action, 'drawIndex', 0) or 0)}",
        ]

        dispatch_dim = getattr(action, "dispatchDimension", None)
        if dispatch_dim is not None:
            draw_tokens.append(f"dispatch:{dispatch_dim}")

        mesh_tokens.extend(draw_tokens)
        return utils.make_signature(mesh_tokens, "mesh")

    def _build_lighting_key(self, used_resource_ids: List[str], constant_layout_tokens: List[str]) -> str:
        keywords = ("light", "shadow", "sun", "env", "probe", "ibl", "sky")
        lighting_tokens: List[str] = []

        for rid in utils.stable_unique_sorted(used_resource_ids):
            name = (self._resource_names.get(rid) or "").lower()
            if any(keyword in name for keyword in keywords):
                lighting_tokens.append(f"res:{rid}")

        for token in constant_layout_tokens:
            lower = token.lower()
            if any(keyword in lower for keyword in keywords):
                lighting_tokens.append(f"cb:{token}")

        if not lighting_tokens:
            for token in constant_layout_tokens:
                if token.startswith("Pixel:") or token.startswith("Compute:"):
                    lighting_tokens.append(f"cb:{token}")

        if not lighting_tokens:
            lighting_tokens.append("none")

        return utils.make_signature(lighting_tokens, "light")

    def _register_shader(self, shader_registry: Dict[str, Dict[str, Any]], shader_item: Dict[str, Any]) -> None:
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

    def _parse_revision1(
        self,
        include_source: bool = False,
        include_context_events: bool = False,
        emit_shaders: bool = False,
    ) -> Dict[str, Any]:
        if self.controller is None:
            raise RuntimeError("Parser is not loaded")

        material_map: Dict[str, Dict[str, Any]] = {}
        shader_registry: Dict[str, Dict[str, Any]] = {}
        used_texture_ids: Set[str] = set()

        pipeline_type = "Unknown"
        try:
            api_props = self.controller.GetAPIProperties()
            pipeline_type = utils.enum_name(getattr(api_props, "pipelineType", None)) or "Unknown"
        except Exception:
            pass

        for action in rdc_utils.list_all_actions(self.controller):
            if not rdc_utils.is_draw_or_dispatch(action):
                continue

            self.controller.SetFrameEvent(action.eventId, True)
            state = self.controller.GetPipelineState()

            shader_items = self._extract_shaders(state, include_source=include_source)
            shader_keys = sorted(set(item["shader_key"] for item in shader_items))

            texture_ids = self._extract_texture_ids(state)
            used_texture_ids.update(texture_ids)
            sampler_ids = self._extract_sampler_ids(state)
            used_resource_ids = self._extract_used_resource_ids(state)
            constant_layout_tokens = self._extract_constant_layout_tokens_from_shaders(shader_items)

            base_features = self._build_base_features(texture_ids, sampler_ids, constant_layout_tokens)
            material_base_key = self._build_material_base_key(base_features)
            variant_key = self._build_variant_key(shader_keys)

            pass_key = self._build_pass_key(action, state, pipeline_type)
            mesh_key = self._build_mesh_key(action, state)
            lighting_key = self._build_lighting_key(used_resource_ids, constant_layout_tokens)
            context_key = utils.make_signature([pass_key, mesh_key, lighting_key], "ctx")

            material_entry = material_map.get(material_base_key)
            if material_entry is None:
                material_entry = {
                    "material_base_key": material_base_key,
                    "base_features": base_features,
                    "_texture_id_set": set(),
                    "_shader_key_set": set(),
                    "_variant_map": {},
                    "_usage_count": 0,
                }
                material_map[material_base_key] = material_entry
            material_entry["_usage_count"] += 1
            material_entry["_texture_id_set"].update(texture_ids)
            material_entry["_shader_key_set"].update(shader_keys)

            if self._texture_output_dir is not None:
                for texture_id in texture_ids:
                    self._ensure_texture_export(texture_id)

            variant_map = material_entry["_variant_map"]
            variant_entry = variant_map.get(variant_key)
            if variant_entry is None:
                variant_entry = {
                    "variant_key": variant_key,
                    "shader_keys": shader_keys,
                    "usage_count": 0,
                    "_context_map": {},
                }
                variant_map[variant_key] = variant_entry
            variant_entry["usage_count"] += 1

            context_map = variant_entry["_context_map"]
            context_entry = context_map.get(context_key)
            if context_entry is None:
                context_entry = {
                    "context_key": context_key,
                    "pass_key": pass_key,
                    "mesh_key": mesh_key,
                    "lighting_key": lighting_key,
                    "usage_count": 0,
                }
                if include_context_events:
                    context_entry["event_ids"] = []
                context_map[context_key] = context_entry

            context_entry["usage_count"] += 1
            if include_context_events:
                context_entry["event_ids"].append(int(action.eventId))

            for item in shader_items:
                self._register_shader(shader_registry, item)

        material_rows: List[Tuple[Dict[str, Any], int]] = []

        for material_entry in material_map.values():
            material_payload = {
                "material_base_key": material_entry["material_base_key"],
                "texture_json_paths": [
                    self._texture_json_path(texture_id) or texture_id
                    for texture_id in sorted(material_entry["_texture_id_set"])
                ],
                "shader_json_paths": [
                    self._shader_json_path(shader_key) or shader_key
                    for shader_key in sorted(material_entry["_shader_key_set"])
                ],
            }

            material_rows.append((material_payload, material_entry["_usage_count"]))

        material_rows.sort(key=lambda item: item[1], reverse=True)
        material_pairs: List[Tuple[str, str]] = []
        for material_payload, _usage in material_rows:
            material_path = self._persist_material_record(
                material_payload.get("material_base_key", ""), material_payload
            )
            if material_path:
                material_pairs.append((str(material_payload.get("material_base_key", "")), material_path))

        summary: Dict[str, Any] = {
            "material_count": len(material_map),
            "texture_count": len(used_texture_ids),
            "shader_count": len(shader_registry),
        }

        artifacts: Dict[str, Any] = {}
        if self._material_output_dir is not None:
            material_index_entries = self._build_index_entries(material_pairs, self._material_output_base_dir)
            index_path = self._write_index_file(
                self._material_output_dir,
                material_index_entries,
                file_name="rdc_material_index.json",
            )
            if index_path:
                artifacts["materials"] = {
                    "index": index_path,
                    "count": len(material_index_entries),
                }
        if self._texture_output_dir is not None:
            texture_pairs: List[Tuple[str, str]] = []
            texture_export_error_count = 0
            for texture_id in sorted(used_texture_ids):
                texture_record = self._ensure_texture_export(texture_id)
                if texture_record.get("export_error"):
                    texture_export_error_count += 1
                texture_path = self._persist_texture_record(texture_id, texture_record)
                if texture_path:
                    texture_pairs.append((str(texture_record.get("texture_compare_key", texture_id)), texture_path))
            texture_index_entries = self._build_index_entries(texture_pairs, self._texture_output_base_dir)
            index_path = self._write_index_file(
                self._texture_output_dir,
                texture_index_entries,
                file_name="rdc_texture_index.json",
            )
            if index_path:
                artifacts["textures"] = {
                    "index": index_path,
                    "count": len(texture_index_entries),
                }
            summary["texture_export_error_count"] = texture_export_error_count
        if self._shader_output_dir is not None:
            shader_rows = sorted(
                shader_registry.values(),
                key=lambda x: (x.get("usage_count", 0), x.get("source_line_count", 0)),
                reverse=True,
            )
            shader_pairs: List[Tuple[str, str]] = []
            for shader_payload in shader_rows:
                shader_path = self._persist_shader_record(shader_payload)
                if shader_path:
                    shader_pairs.append((str(shader_payload.get("shader_key", "")), shader_path))
            shader_index_entries = self._build_index_entries(shader_pairs, self._shader_output_base_dir)
            index_path = self._write_index_file(
                self._shader_output_dir,
                shader_index_entries,
                file_name="rdc_shader_index.json",
            )
            if index_path:
                artifacts["shaders"] = {
                    "index": index_path,
                    "count": len(shader_index_entries),
                }

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "capture_file": Path(self.filename).name,
            "capture_id": self._capture_id(),
            "summary": summary,
            "artifacts": artifacts,
        }

    def _parse_legacy(self, include_source: bool = False) -> Dict[str, Any]:
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

        payload: Dict[str, Any] = {
            "capture_file": Path(self.filename).name,
            "summary": summary,
            "materials": materials,
            "shaders": shaders,
        }

        if include_source and self._source_output_dir is not None:
            shader_dir = (
                self._source_output_dir.relative_to(self._source_output_base_dir).as_posix()
                if self._source_output_base_dir is not None
                else str(self._source_output_dir)
            )
            payload["artifacts"] = {"shader_sources_dir": shader_dir}

        return payload

    def parse(
        self,
        include_source: bool = False,
        schema: str = "1",
        include_context_events: bool = False,
        emit_shaders: bool = False,
        source_output_dir: Optional[str] = None,
        material_output_dir: Optional[str] = None,
        texture_output_dir: Optional[str] = None,
        shader_output_dir: Optional[str] = None,
        export_texture_images: bool = True,
    ) -> Dict[str, Any]:
        normalized = str(schema or "1").strip().lower()
        self._export_texture_images = bool(export_texture_images)
        if normalized in {"1", "v1", "rev1", "first"}:
            self._configure_shader_output_dir(shader_output_dir)
            self._configure_source_output_dir(shader_output_dir if include_source else None)
            self._configure_material_output_dir(material_output_dir)
            self._configure_texture_output_dir(texture_output_dir)
        else:
            self._configure_shader_output_dir(None)
            self._configure_source_output_dir(source_output_dir if include_source else None)
            self._configure_material_output_dir(None)
            self._configure_texture_output_dir(None)
        if normalized in {"1", "v1", "rev1", "first"}:
            return self._parse_revision1(
                include_source=include_source,
                include_context_events=include_context_events,
                emit_shaders=emit_shaders,
            )

        return self._parse_legacy(include_source=include_source)


def parse_capture_material_shader(
    filename: str,
    include_source: bool = False,
    schema: str = "1",
    include_context_events: bool = False,
    emit_shaders: bool = False,
    source_output_dir: Optional[str] = None,
    material_output_dir: Optional[str] = None,
    texture_output_dir: Optional[str] = None,
    shader_output_dir: Optional[str] = None,
    export_texture_images: bool = True,
) -> Dict[str, Any]:
    with MaterialShaderParser(filename) as parser:
        return parser.parse(
            include_source=include_source,
            schema=schema,
            include_context_events=include_context_events,
            emit_shaders=emit_shaders,
            source_output_dir=source_output_dir,
            material_output_dir=material_output_dir,
            texture_output_dir=texture_output_dir,
            shader_output_dir=shader_output_dir,
            export_texture_images=export_texture_images,
        )
