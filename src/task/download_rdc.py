from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path
import requests
from requests.auth import HTTPBasicAuth
from urllib3.exceptions import InsecureRequestWarning

from common import cfg

from . import task_manager


requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)


def _resolve_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (Path.cwd() / path).resolve()


def _ensure_directory(directory: Path) -> Path:
    resolved = directory.resolve()
    if resolved.exists() and not resolved.is_dir():
        raise NotADirectoryError(f"expected directory path, got file: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _clean_directory(directory: Path) -> None:
    for child in directory.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _flatten_extracted_rdc_files(output_dir: Path) -> int:
    rdc_files = sorted([path for path in output_dir.rglob("*.rdc") if path.is_file()])
    if not rdc_files:
        raise FileNotFoundError(f"no .rdc file found after extract: {output_dir}")

    moved_count = 0
    for src in rdc_files:
        if src.parent == output_dir:
            continue

        target = output_dir / src.name
        if target.exists():
            stem = target.stem
            suffix = target.suffix
            index = 1
            while True:
                candidate = output_dir / f"{stem}_{index}{suffix}"
                if not candidate.exists():
                    target = candidate
                    break
                index += 1

        src.replace(target)
        moved_count += 1

    # Remove extracted wrapper folders and any non-rdc payload files.
    for path in sorted(output_dir.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass
            continue
        if path.suffix.lower() != ".rdc":
            path.unlink(missing_ok=True)

    return moved_count


def _normalize_udt_test_id(udt_url: str) -> str:
    value = str(udt_url).strip()
    if not value:
        raise ValueError("udt_url is empty")

    match = re.search(r"/tests/([^/?#]+)/?", value)
    if match:
        return match.group(1)
    return value


def _download_rdc_resources(
    *,
    project: str,
    app_id: str,
    secret_key: str,
    udt_url: str,
    device_id: str,
    output_dir: Path,
) -> Path:
    output_dir = _ensure_directory(output_dir)
    _clean_directory(output_dir)

    test_id = _normalize_udt_test_id(udt_url)
    api_uri = f"https://udt.woa.com/v1/api/tests/{test_id}/devices/{device_id}/resources"
    auth = HTTPBasicAuth(app_id, secret_key)

    print(f"download_rdc start: test_id={test_id}, device_id={device_id}, project={project}")
    print(f"download_rdc output_dir: {output_dir}")

    response = requests.get(
        api_uri,
        params={"project": project},
        auth=auth,
        verify=False,
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()

    resource_list = payload.get("data", {}).get("resource_list", [])
    zip_url = next((item.get("url", "") for item in resource_list if item.get("name") == "RenderDoc.zip"), "")
    if not zip_url:
        raise FileNotFoundError("RenderDoc.zip was not found in the UDT resource list")

    zip_path = output_dir / "RenderDoc.zip"
    print("download_rdc downloading archive...")
    zip_response = requests.get(
        zip_url,
        auth=auth,
        verify=False,
        timeout=300,
    )
    zip_response.raise_for_status()
    zip_path.write_bytes(zip_response.content)

    print("download_rdc extracting archive...")
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(output_dir)

    zip_path.unlink(missing_ok=True)
    moved_count = _flatten_extracted_rdc_files(output_dir)
    root_rdc_count = len(list(output_dir.glob("*.rdc")))
    print(f"download_rdc flatten done: moved={moved_count}, root_rdc={root_rdc_count}")
    print(f"download_rdc done: {output_dir}")
    return output_dir


@task_manager.manager.register
class DownloadRdcTask:
    TASK_ID = "download_rdc"

    def execute(self, args, params):
        project = str(params.get("project", "") or "").strip()
        secret_key = str(params.get("key", "") or "").strip()
        app_id = str(params.get("id", "") or "").strip()
        udt_url = str(params.get("udt_url", "") or "").strip()
        device_id = str(params.get("device_id", "") or "").strip()

        missing = []
        if not project:
            missing.append("project")
        if not secret_key:
            missing.append("key")
        if not app_id:
            missing.append("id")
        if not udt_url:
            missing.append("udt_url")
        if not device_id:
            missing.append("device_id")
        if missing:
            raise RuntimeError("missing required params: " + ", ".join(missing))

        output_dir_value = str(
            params.get("output")
            or params.get("output_dir")
            or params.get("save_dir")
            or cfg.save_dir
        )
        output_dir = _resolve_path(output_dir_value)

        _download_rdc_resources(
            project=project,
            app_id=app_id,
            secret_key=secret_key,
            udt_url=udt_url,
            device_id=device_id,
            output_dir=output_dir,
        )
