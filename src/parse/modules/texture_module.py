from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import renderdoc as rd

from .. import utils
from .io_utils import relative_artifact_path, safe_file_part, sha256_file


class TextureModule:
    def __init__(self) -> None:
        self.controller: Optional[rd.ReplayController] = None
        self.resource_names: Dict[str, str] = {}
        self.texture_ids: Set[str] = set()
        self.texture_desc_map: Dict[str, Any] = {}
        self.output_dir: Optional[Path] = None
        self.output_base_dir: Optional[Path] = None
        self.shared_image_dir: Optional[Path] = None
        self._image_hash_map: Dict[str, Path] = {}
        self.export_map: Dict[str, Dict[str, Any]] = {}
        self.export_texture_images: bool = True

    def set_capture_context(
        self,
        controller: Optional[rd.ReplayController],
        resource_names: Dict[str, str],
        texture_ids: Set[str],
        texture_desc_map: Dict[str, Any],
    ) -> None:
        self.controller = controller
        self.resource_names = resource_names
        self.texture_ids = texture_ids
        self.texture_desc_map = texture_desc_map

    def set_export_texture_images(self, enabled: bool) -> None:
        self.export_texture_images = bool(enabled)

    def configure_output_dir(self, texture_output_dir: Optional[str]) -> None:
        self.output_dir = None
        self.output_base_dir = None
        self.shared_image_dir = None
        self._image_hash_map = {}
        self.export_map = {}
        if not texture_output_dir:
            return

        texture_dir = Path(texture_output_dir).resolve()
        texture_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir = texture_dir
        self.output_base_dir = texture_dir.parent
        shared_image_dir = texture_dir / "_shared_images"
        shared_image_dir.mkdir(parents=True, exist_ok=True)
        self.shared_image_dir = shared_image_dir

    @staticmethod
    def build_texture_id_set(controller: Optional[rd.ReplayController]) -> Set[str]:
        if controller is None:
            return set()

        tex_ids: Set[str] = set()
        try:
            for tex in controller.GetTextures():
                rid = utils.normalize_resource_id(tex.resourceId)
                if rid:
                    tex_ids.add(rid)
        except Exception:
            return tex_ids
        return tex_ids

    @staticmethod
    def build_texture_desc_map(controller: Optional[rd.ReplayController]) -> Dict[str, Any]:
        if controller is None:
            return {}

        texture_map: Dict[str, Any] = {}
        try:
            for tex in controller.GetTextures():
                rid = utils.normalize_resource_id(getattr(tex, "resourceId", None))
                if rid:
                    texture_map[rid] = tex
        except Exception:
            return texture_map

        return texture_map

    def _texture_dir_for_id(self, texture_id: str) -> Optional[Path]:
        if self.output_dir is None:
            return None
        return self.output_dir / safe_file_part(texture_id.replace(":", "_"))

    def texture_json_path(self, texture_id: str) -> Optional[str]:
        texture_dir = self._texture_dir_for_id(texture_id)
        if texture_dir is None:
            return None
        return relative_artifact_path(texture_dir / "rdc_texture.json", self.output_base_dir)

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

    def _shared_image_path_for_sha(self, image_sha256: str) -> Optional[Path]:
        if self.shared_image_dir is None or not image_sha256:
            return None
        return self.shared_image_dir / f"img_{image_sha256}.png"

    def texture_compare_key(self, texture_id: str) -> str:
        record = self.export_map.get(texture_id) or self.ensure_texture_export(texture_id)
        return self._compute_texture_compare_key(texture_id, record)

    def ensure_texture_export(self, texture_id: str) -> Dict[str, Any]:
        cached = self.export_map.get(texture_id)
        if cached and cached.get("image_path"):
            return cached

        record: Dict[str, Any] = dict(cached or {})
        record.setdefault("resource_id", texture_id)
        record.setdefault("resource_name", self.resource_names.get(texture_id, ""))

        tex_desc = self.texture_desc_map.get(texture_id)
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
            or not self.export_texture_images
        ):
            self.export_map[texture_id] = record
            return record

        texture_dir.mkdir(parents=True, exist_ok=True)
        temp_export_path = texture_dir / "_export_tmp.png"
        if temp_export_path.exists():
            try:
                temp_export_path.unlink()
            except Exception:
                pass

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

            result = self.controller.SaveTexture(save_data, str(temp_export_path))
            ok = bool(result)
            try:
                ok = bool(result.OK())
            except Exception:
                pass

            if ok:
                try:
                    image_sha256 = sha256_file(temp_export_path)
                    shared_path = self._image_hash_map.get(image_sha256)
                    if shared_path is None:
                        shared_path = self._shared_image_path_for_sha(image_sha256)

                    if shared_path is None:
                        raise RuntimeError("shared image output dir is not configured")

                    if shared_path.exists():
                        temp_export_path.unlink()
                    else:
                        temp_export_path.replace(shared_path)

                    self._image_hash_map[image_sha256] = shared_path
                    record["image_sha256"] = image_sha256
                    record["image_path"] = relative_artifact_path(shared_path, self.output_base_dir)
                except Exception:
                    if temp_export_path.exists():
                        try:
                            temp_export_path.unlink()
                        except Exception:
                            pass
            else:
                if temp_export_path.exists():
                    try:
                        temp_export_path.unlink()
                    except Exception:
                        pass
                msg = ""
                try:
                    msg = result.Message()
                except Exception:
                    msg = ""
                if msg:
                    record["export_error"] = msg
        except Exception as exc:
            if temp_export_path.exists():
                try:
                    temp_export_path.unlink()
                except Exception:
                    pass
            record["export_error"] = str(exc)

        if "texture_compare_key" not in record:
            record["texture_compare_key"] = self._compute_texture_compare_key(texture_id, record)

        self.export_map[texture_id] = record
        return record

    def persist_texture_record(self, texture_id: str, record: Optional[Dict[str, Any]] = None) -> Optional[str]:
        if record is None:
            record = self.ensure_texture_export(texture_id)
        texture_dir = self._texture_dir_for_id(texture_id)
        if texture_dir is None:
            return None

        texture_dir.mkdir(parents=True, exist_ok=True)
        target_path = texture_dir / "rdc_texture.json"
        target_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return relative_artifact_path(target_path, self.output_base_dir)

    def _collect_resource_ids_from_used_descriptors(
        self, used_descriptors, texture_only: bool = False
    ) -> Set[str]:
        res_ids: Set[str] = set()
        for used in used_descriptors or []:
            descriptor = getattr(used, "descriptor", None)
            if descriptor is not None:
                for attr in ("resource", "view", "secondary"):
                    rid = utils.normalize_resource_id(getattr(descriptor, attr, None))
                    if rid and (not texture_only or rid in self.texture_ids):
                        res_ids.add(rid)

            sampler_desc = getattr(used, "sampler", None)
            if sampler_desc is not None:
                for attr in ("object", "ycbcrSampler"):
                    rid = utils.normalize_resource_id(getattr(sampler_desc, attr, None))
                    if rid and (not texture_only or rid in self.texture_ids):
                        res_ids.add(rid)
        return res_ids

    def extract_texture_ids(self, state: rd.PipeState, shader_stages: List[rd.ShaderStage]) -> List[str]:
        tex_ids: Set[str] = set()
        for stage in shader_stages:
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

    def extract_used_resource_ids(self, state: rd.PipeState, shader_stages: List[rd.ShaderStage]) -> List[str]:
        resource_ids: Set[str] = set()
        for stage in shader_stages:
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
