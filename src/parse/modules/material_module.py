from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .. import utils
from .io_utils import relative_artifact_path, safe_file_part


class MaterialModule:
    def __init__(self) -> None:
        self.resource_names: Dict[str, str] = {}
        self.output_dir: Optional[Path] = None
        self.output_base_dir: Optional[Path] = None

    def set_resource_names(self, resource_names: Dict[str, str]) -> None:
        self.resource_names = resource_names

    def configure_output_dir(self, material_output_dir: Optional[str]) -> None:
        self.output_dir = None
        self.output_base_dir = None
        if not material_output_dir:
            return

        material_dir = Path(material_output_dir).resolve()
        material_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir = material_dir
        self.output_base_dir = material_dir.parent

    def _material_dir_for_key(self, material_base_key: str) -> Optional[Path]:
        if self.output_dir is None:
            return None
        return self.output_dir / safe_file_part(material_base_key.replace(":", "_"))

    @staticmethod
    def normalize_token(value: str) -> str:
        return str(value or "").strip().lower()

    def persist_material_record(self, material_base_key: str, material_payload: Dict[str, Any]) -> Optional[str]:
        if self.output_dir is None:
            return None
        material_dir = self._material_dir_for_key(material_base_key)
        if material_dir is None:
            return None

        material_dir.mkdir(parents=True, exist_ok=True)
        target_path = material_dir / "rdc_material.json"
        target_path.write_text(json.dumps(material_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return relative_artifact_path(target_path, self.output_base_dir)

    def _texture_signature_values(
        self, texture_ids: List[str], texture_compare_key_func: Callable[[str], str]
    ) -> List[str]:
        return [texture_compare_key_func(texture_id) for texture_id in sorted(set(texture_ids))]

    def _sampler_signature_values(self, sampler_ids: List[str]) -> List[str]:
        values: List[str] = []
        for sampler_id in sorted(set(sampler_ids)):
            sampler_name = str(self.resource_names.get(sampler_id, "") or "").strip()
            if sampler_name:
                values.append(f"name:{sampler_name}")
            else:
                values.append(f"id:{sampler_id}")
        return values

    def build_base_features(
        self,
        texture_ids: List[str],
        sampler_ids: List[str],
        constant_layout_tokens: List[str],
        texture_compare_key_func: Callable[[str], str],
    ) -> Dict[str, str]:
        texture_values = self._texture_signature_values(texture_ids, texture_compare_key_func)
        sampler_values = self._sampler_signature_values(sampler_ids)
        return {
            "texture_signature": utils.make_signature(texture_values, "tex"),
            "sampler_signature": utils.make_signature(sampler_values, "smp"),
            "constant_layout_signature": utils.make_signature(constant_layout_tokens, "cbuf"),
        }

    @staticmethod
    def build_material_base_key(base_features: Dict[str, str]) -> str:
        return utils.make_signature(
            [
                base_features.get("texture_signature", ""),
                base_features.get("sampler_signature", ""),
                base_features.get("constant_layout_signature", ""),
            ],
            "mat",
        )

    @staticmethod
    def build_variant_key(shader_keys: List[str]) -> str:
        return utils.make_signature(shader_keys, "var")

    @staticmethod
    def build_material_instance_key(material_instance_name: str) -> str:
        name = str(material_instance_name or "").strip().lower()
        if not name:
            return "mat:none"
        return utils.make_signature([f"mi:{name}"], "mat")

    @staticmethod
    def build_material_stable_key(
        shader_keys: List[str],
        material_instance_name: str,
        mesh_name: str,
        pass_channel: str,
    ) -> str:
        tokens: List[str] = []
        for shader_key in sorted(set(shader_keys)):
            text = str(shader_key or "").strip()
            if text:
                tokens.append(f"shader:{text}")

        mi_text = str(material_instance_name or "").strip()
        mesh_text = str(mesh_name or "").strip()
        pass_text = str(pass_channel or "").strip()
        if mi_text:
            tokens.append(f"mi:{mi_text.lower()}")
        if mesh_text:
            tokens.append(f"mesh:{mesh_text.lower()}")
        if pass_text:
            tokens.append(f"pass:{pass_text.lower()}")

        return utils.make_signature(tokens, "mat")

    @staticmethod
    def build_usage_key(
        material_instance_name: str,
        mesh_name: str,
        pass_channel: str,
        stage_shader_map: Dict[str, str],
    ) -> str:
        tokens: List[str] = [
            f"mi:{str(material_instance_name or '').strip().lower() or 'none'}",
            f"mesh:{str(mesh_name or '').strip().lower() or 'none'}",
            f"pass:{str(pass_channel or '').strip().lower() or 'none'}",
        ]
        for stage in sorted(stage_shader_map):
            shader_key = str(stage_shader_map.get(stage, "") or "").strip()
            if shader_key:
                tokens.append(f"{stage}:{shader_key}")
        return utils.make_signature(tokens, "usage")

    @staticmethod
    def build_shader_set_key(stage_shader_map: Dict[str, str]) -> str:
        tokens = []
        for stage in sorted(stage_shader_map):
            shader_key = str(stage_shader_map.get(stage, "") or "").strip()
            if shader_key:
                tokens.append(f"{stage}:{shader_key}")
        return utils.make_signature(tokens, "shset")

    @staticmethod
    def build_content_signature(
        mesh_names: List[str],
        pass_channels: List[str],
        shader_sets: List[Dict[str, str]],
    ) -> str:
        tokens: List[str] = []
        for mesh_name in sorted(set(str(x or "").strip().lower() for x in mesh_names if str(x or "").strip())):
            tokens.append(f"mesh:{mesh_name}")
        for pass_channel in sorted(
            set(str(x or "").strip().lower() for x in pass_channels if str(x or "").strip())
        ):
            tokens.append(f"pass:{pass_channel}")

        shader_set_tokens: List[str] = []
        for shader_set in shader_sets:
            if not isinstance(shader_set, dict):
                continue
            stage_tokens = []
            for stage in sorted(shader_set):
                shader_key = str(shader_set.get(stage, "") or "").strip()
                if shader_key:
                    stage_tokens.append(f"{stage}:{shader_key}")
            if stage_tokens:
                shader_set_tokens.append(";".join(stage_tokens))

        for shader_set_token in sorted(set(shader_set_tokens)):
            tokens.append(f"shader_set:{shader_set_token}")

        return utils.make_signature(tokens, "sig")
