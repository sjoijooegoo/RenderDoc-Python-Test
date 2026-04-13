from __future__ import annotations

from typing import Any, Dict

from .rdc_parse_pipeline import RdcParsePipeline


class RDCParser:
    """Compatibility wrapper around the RDC parse pipeline."""

    def __init__(self, filename: str):
        self.filename = filename
        self._parser = RdcParsePipeline(filename)

    def load(self) -> None:
        self._parser.load()

    def parse(
        self,
        include_source: bool = False,
        schema: str = "1",
        source_output_dir: str | None = None,
        material_output_dir: str | None = None,
        texture_output_dir: str | None = None,
        shader_output_dir: str | None = None,
        pass_output_dir: str | None = None,
        export_texture_images: bool = False,
    ) -> Dict[str, Any]:
        return self._parser.parse(
            include_source=include_source,
            schema=schema,
            source_output_dir=source_output_dir,
            material_output_dir=material_output_dir,
            texture_output_dir=texture_output_dir,
            shader_output_dir=shader_output_dir,
            pass_output_dir=pass_output_dir,
            export_texture_images=export_texture_images,
        )

    def shutdown(self) -> None:
        self._parser.shutdown()

    def __enter__(self):
        self.load()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
