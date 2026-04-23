'''
author: v_sycisong
LastEditors: v_sycisong
'''
"""
author: v_sycisong
LastEditors: v_sycisong
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


class CosParams:
    def __init__(self, rdc_path: Optional[str] = None):
        self.build_num: str = os.getenv("BuildNum", "1234")
        self.tex_quality: str = os.getenv("TexQuality", "1")
        self.map_name: str = os.getenv("RunMap", "Forest_WP")
        self.time_str: str = os.getenv("Time", datetime.now().strftime("%m%d_%H%M"))
        self.rand_str: str = uuid.uuid4().hex[:8]
        self.rdc_id: str = self._build_rdc_id(rdc_path)

    @staticmethod
    def _build_rdc_id(rdc_path: Optional[str]) -> str:
        if not rdc_path:
            return ""
        try:
            return Path(str(rdc_path)).stem
        except Exception:
            return ""
        
    def to_json_dict(self):
        return {
            "build_num": self.build_num,
            "tex_quality": self.tex_quality,
            "rdc_id": self.rdc_id,
            "time": self.time_str,
            "map_name": self.map_name,
        }

    def to_cos_package_dir_name(self) -> str:
        run_suffix = f"{self.time_str}_{self.rand_str}"
        return f"rdc_{self.build_num}_{self.tex_quality}_{self.rdc_id}_{run_suffix}"
