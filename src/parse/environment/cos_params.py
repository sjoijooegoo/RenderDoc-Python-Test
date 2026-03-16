"""
author: v_sycisong
LastEditors: v_sycisong
"""

from __future__ import annotations

import os
from datetime import datetime


class CosParams:
    def __init__(self):
        self.build_num: str = os.getenv("BuildNum", "1234")
        self.tex_quality: str = os.getenv("TexQuality", "1")
        self.map_name: str = os.getenv("RunMap", "Forest_WP")
        self.time_str: str = datetime.now().strftime("%Y%m%d%H%M%S")
        
    def to_json_dict(self):
        return {
            "build_num": self.build_num,
            "tex_quality": self.tex_quality,
            "map_name": self.map_name,
        }

    def to_cos_package_dir_name(self) -> str:
        return f"rdc_{self.build_num}_{self.tex_quality}_{self.time_str}"
