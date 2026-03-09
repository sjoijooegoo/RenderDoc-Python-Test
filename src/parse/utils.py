from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable, List, Optional


def enum_name(value: Any) -> str:
    if value is None:
        return ""
    return value.name if hasattr(value, "name") else str(value)


def count_lines(text: Optional[str]) -> int:
    if not text:
        return 0
    return len(text.splitlines())


def safe_resource_id(resource: Optional[Dict[str, Any]]) -> str:
    if not resource:
        return ""
    resource_id = resource.get("id")
    return str(resource_id) if resource_id else ""


def normalize_resource_id(value: Any) -> str:
    if value is None:
        return ""
    as_str = str(value)
    return "" if as_str in {"0", "ResourceId::0", "ResourceId::Null"} else as_str


def stable_unique_sorted(values: Iterable[Any]) -> List[str]:
    cleaned: List[str] = []
    seen = set()
    for value in values:
        text = str(value).strip() if value is not None else ""
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    cleaned.sort()
    return cleaned


def make_signature(values: Iterable[Any], prefix: str) -> str:
    normalized = stable_unique_sorted(values)
    if not normalized:
        return f"{prefix}:none"
    digest = hashlib.md5("|".join(normalized).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def make_shader_key(shader_info: Dict[str, Any]) -> str:
    source_md5 = shader_info.get("source_md5")
    if source_md5:
        return f"md5:{source_md5}"

    source_files = shader_info.get("source_files") or []
    merged_sources = []
    for src in source_files:
        content = src.get("content") or src.get("contents") or ""
        if content:
            merged_sources.append(content)
    if merged_sources:
        digest = hashlib.md5("\n".join(merged_sources).encode("utf-8")).hexdigest()
        return f"md5:{digest}"

    resource = shader_info.get("resource")
    if resource:
        resource_id = safe_resource_id(resource)
        if resource_id:
            return f"resource:{resource_id}"

    stage = shader_info.get("stage") or ""
    entry = shader_info.get("entry_point") or ""
    return f"{stage}:{entry}"
