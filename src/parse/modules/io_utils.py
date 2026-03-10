from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Optional


def safe_file_part(text: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", text.strip())
    safe = safe.strip("._")
    return safe or "source"


def relative_artifact_path(file_path: Path, base_dir: Optional[Path]) -> str:
    if base_dir is None:
        return str(file_path)
    return file_path.relative_to(base_dir).as_posix()


def sha256_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
