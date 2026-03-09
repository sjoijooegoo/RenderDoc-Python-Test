from __future__ import annotations

from typing import Any, Dict

from .material_shader_parser import MaterialShaderParser


class RDCParser:
    """Compatibility wrapper around the new material/shader parser."""

    def __init__(self, filename: str):
        self.filename = filename
        self._parser = MaterialShaderParser(filename)

    def load(self) -> None:
        self._parser.load()

    def parse(self, include_source: bool = False) -> Dict[str, Any]:
        return self._parser.parse(include_source=include_source)

    def shutdown(self) -> None:
        self._parser.shutdown()

    def __enter__(self):
        self.load()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
