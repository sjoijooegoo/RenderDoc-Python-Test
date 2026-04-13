from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import renderdoc as rd

from .. import rdc_utils
from .. import utils
from .io_utils import relative_artifact_path, safe_file_part


class PassModule:
    def __init__(self) -> None:
        self.controller: Optional[rd.ReplayController] = None
        self.output_dir: Optional[Path] = None
        self.output_base_dir: Optional[Path] = None

    def set_controller(self, controller: Optional[rd.ReplayController]) -> None:
        self.controller = controller

    def configure_output_dir(self, pass_output_dir: Optional[str]) -> None:
        self.output_dir = None
        self.output_base_dir = None
        if not pass_output_dir:
            return

        pass_dir = Path(pass_output_dir).resolve()
        pass_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir = pass_dir
        self.output_base_dir = pass_dir.parent

    def _pass_dir_for_key(self, pass_key: str) -> Optional[Path]:
        if self.output_dir is None:
            return None
        return self.output_dir / safe_file_part(pass_key.replace(":", "_"))

    def persist_pass_record(self, pass_payload: Dict[str, Any]) -> Optional[str]:
        pass_key = str(pass_payload.get("pass_key", "") or "")
        pass_dir = self._pass_dir_for_key(pass_key)
        if pass_dir is None:
            return None

        pass_dir.mkdir(parents=True, exist_ok=True)
        target_path = pass_dir / "rdc_pass.json"
        target_path.write_text(json.dumps(pass_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return relative_artifact_path(target_path, self.output_base_dir)

    def extract_pass_features(
        self, action: rd.ActionDescription, state: rd.PipeState, pipeline_type: str
    ) -> Dict[str, Any]:
        marker_path = ""
        if self.controller is not None:
            marker_path = rdc_utils.get_marker_path(action, self.controller)
        marker_path = marker_path or "root"
        marker_context = self.extract_marker_context(marker_path)
        pass_channel = marker_context.get("pass_channel", "")

        pass_tokens = [
            f"api:{pipeline_type or 'Unknown'}",
            f"channel:{pass_channel or 'none'}",
            f"marker:{marker_path}",
        ]

        return {
            "pipeline_type": pipeline_type or "Unknown",
            "marker_path": marker_path,
            "pass_channel": pass_channel,
            "pass_key": utils.make_signature(pass_tokens, "pass"),
        }

    @staticmethod
    def extract_marker_context(marker_path: str) -> Dict[str, str]:
        parts = [segment.strip() for segment in str(marker_path or "").split("/") if segment.strip()]
        if not parts:
            return {
                "pass_channel": "",
                "material_instance_name": "",
                "mesh_name": "",
                "marker_leaf": "",
            }

        marker_leaf = parts[-1]
        label = re.sub(r"\s*\(\d+\s+instances?\)\s*$", "", marker_leaf, flags=re.IGNORECASE)
        tokens = [token.strip() for token in label.split() if token.strip()]

        def _looks_like_material_instance(name: str) -> bool:
            lower = str(name or "").strip().lower()
            if not lower:
                return False
            if lower.startswith(("mi_", "mid_", "m_inst_", "materialinstance_")):
                return True
            if lower.startswith("mi") and "_" in lower:
                return True
            return False

        def _looks_like_pass_channel(name: str) -> bool:
            lower = str(name or "").strip().lower()
            if not lower:
                return False
            keywords = (
                "pass",
                "view",
                "prepass",
                "lighting",
                "shadow",
                "transluc",
                "post",
                "ui",
                "scenecolor",
                "depth",
                "gbuffer",
            )
            return any(keyword in lower for keyword in keywords)

        def _normalize_pass_channel(name: str) -> str:
            channel = str(name or "").strip()
            if not channel:
                return ""
            if re.search(r"[\s=:/()]", channel):
                return ""
            lower = channel.lower()
            if any(keyword in lower for keyword in ("pass", "view", "post", "shadow", "decal", "lighting")):
                return channel
            return ""

        material_instance_name = ""
        mesh_name = ""
        if tokens and _looks_like_material_instance(tokens[0]):
            material_instance_name = tokens[0]
            if len(tokens) >= 2:
                mesh_name = tokens[1]
                if mesh_name == "=":
                    mesh_name = ""

        leaf_is_channel = _looks_like_pass_channel(marker_leaf)
        segment_candidates = parts if (leaf_is_channel and not material_instance_name) else parts[:-1]

        pass_channel = ""
        for segment in reversed(segment_candidates):
            if _looks_like_pass_channel(segment):
                pass_channel = segment
                break

        if not pass_channel:
            if leaf_is_channel and not material_instance_name:
                pass_channel = marker_leaf
            elif len(parts) >= 2:
                pass_channel = parts[-2]
            else:
                pass_channel = parts[-1]

        pass_channel = _normalize_pass_channel(pass_channel)
        return {
            "pass_channel": pass_channel,
            "material_instance_name": material_instance_name,
            "mesh_name": mesh_name,
            "marker_leaf": marker_leaf,
        }

    @staticmethod
    def _bound_buffer_token(bound_buffer: Any) -> str:
        if bound_buffer is None:
            return ""
        rid = utils.normalize_resource_id(getattr(bound_buffer, "resourceId", None))
        if not rid:
            return ""

        byte_offset = int(getattr(bound_buffer, "byteOffset", 0) or 0)
        byte_stride = int(getattr(bound_buffer, "byteStride", 0) or 0)
        byte_size = int(getattr(bound_buffer, "byteSize", 0) or 0)
        return f"{rid}:{byte_offset}:{byte_stride}:{byte_size}"

    def build_mesh_key(self, action: rd.ActionDescription, state: rd.PipeState) -> str:
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

    @staticmethod
    def build_lighting_key(
        used_resource_ids: List[str], constant_layout_tokens: List[str], resource_names: Dict[str, str]
    ) -> str:
        keywords = ("light", "shadow", "sun", "env", "probe", "ibl", "sky")
        lighting_tokens: List[str] = []

        for rid in utils.stable_unique_sorted(used_resource_ids):
            name = (resource_names.get(rid) or "").lower()
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
