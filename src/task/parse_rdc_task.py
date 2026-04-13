from __future__ import annotations

import concurrent.futures
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import List, Optional

from common import cfg
from parse.environment import CosParams
from parse.rdc_parse_pipeline import parse_capture_rdc

from . import task_manager


def _resolve_path(path_value: str, base_dir: Optional[Path] = None) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    if base_dir is not None:
        candidate = (base_dir / path).resolve()
        if candidate.exists():
            return candidate
    return (Path.cwd() / path).resolve()


def _to_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _to_int(value: Optional[str], default: int = 1) -> int:
    if value is None:
        return default
    try:
        parsed = int(str(value).strip())
    except Exception:
        return default
    return parsed if parsed > 0 else default


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    safe = safe.strip("._")
    return safe or "capture"


def _safe_output_path(value: str) -> Optional[str]:
    raw_parts = re.split(r"[\\/]+", str(value).strip())
    parts = [_safe_name(part) for part in raw_parts if str(part).strip()]
    if not parts:
        return None
    return Path(*parts).as_posix()


def _find_latest_rdc(save_dir: Path) -> Optional[Path]:
    if not save_dir.exists():
        return None
    files = sorted(save_dir.glob("*.rdc"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _list_rdc_files(dir_path: Path) -> List[Path]:
    if not dir_path.exists() or not dir_path.is_dir():
        return []
    return sorted(
        [path for path in dir_path.glob("*.rdc") if path.is_file()],
        key=lambda path: path.name.lower(),
    )


def _reset_capture_output(capture_folder: Path) -> None:
    for name in ("rdc_material", "rdc_texture", "rdc_shader", "rdc_pass", "_shared_sources", "shader_sources"):
        target = capture_folder / name
        if target.exists() and target.is_dir():
            shutil.rmtree(target)

    entry = capture_folder / "rdc_entry.json"
    if entry.exists() and entry.is_file():
        entry.unlink()


def _resolve_output_folder_name(rdc_path: Path, params) -> Optional[str]:
    output_path_arg = params.get("output_path")
    if output_path_arg is not None and str(output_path_arg).strip():
        return _safe_output_path(str(output_path_arg))

    output_arg = params.get("output") or params.get("ouput")
    if output_arg is None or not str(output_arg).strip():
        return None
    output_name = _safe_name(str(output_arg).strip())
    if output_name.lower() == "name":
        return _safe_name(rdc_path.stem)
    return output_name


def _resolve_batch_output_folder_name(rdc_path: Path, params) -> str:
    output_arg = params.get("output") or params.get("ouput")
    if output_arg is None or not str(output_arg).strip():
        return _safe_name(rdc_path.stem)

    output_name = _safe_name(str(output_arg).strip())
    if output_name.lower() == "name":
        return _safe_name(rdc_path.stem)
    return f"{output_name}/{_safe_name(rdc_path.stem)}"


def _resolve_artifact_root(capture_folder: Path, params, cos_params: CosParams) -> Path:
    pkg_value = str(params.get("pkg", "") or "").strip().lower()
    if pkg_value != "cos":
        return capture_folder

    package_name = _safe_name(cos_params.to_cos_package_dir_name())
    return capture_folder / package_name


def _resolve_artifact_package_path(capture_folder: Path, artifact_root: Path, params) -> Optional[Path]:
    pkg_value = str(params.get("pkg", "") or "").strip().lower()
    if pkg_value != "cos":
        return None
    return capture_folder / f"{artifact_root.name}.zip"


def _reset_packaged_output(
    capture_folder: Path,
    artifact_root: Path,
    artifact_package_path: Optional[Path],
) -> None:
    _reset_capture_output(capture_folder)

    if artifact_root != capture_folder and artifact_root.exists() and artifact_root.is_dir():
        shutil.rmtree(artifact_root)

    if artifact_package_path is not None:
        for zip_path in capture_folder.glob("rdc_*.zip"):
            if zip_path.exists() and zip_path.is_file():
                zip_path.unlink()


def _prefix_artifact_paths(payload, capture_folder: Path, artifact_root: Path) -> None:
    return


def _create_artifact_zip(artifact_root: Path, artifact_package_path: Path) -> None:
    artifact_package_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(artifact_package_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for file_path in sorted(artifact_root.rglob("*")):
            if not file_path.is_file():
                continue
            arcname = file_path.relative_to(artifact_root).as_posix()
            zip_file.write(file_path, arcname=arcname)


def _build_child_command(task_id: str, params) -> List[str]:
    if getattr(sys, "frozen", False):
        command = [sys.executable, task_id]
    else:
        repo_root = Path(__file__).resolve().parents[2]
        command = [sys.executable, str(repo_root / "src" / "main.py"), task_id]

    for key, value in params.items():
        command.append(f"{key}={value}")
    return command


def _run_single_rdc_subprocess(rdc_path: Path, params, output_folder_name: str) -> dict:
    child_params = {}
    for key, value in params.items():
        if key in {"dir", "workers", "output", "ouput", "rdc", "input", "file", "path"}:
            continue
        child_params[key] = value

    child_params["rdc"] = str(rdc_path)
    child_params["output_path"] = output_folder_name

    completed = subprocess.run(_build_child_command("rdc_parse", child_params), check=False)
    return {
        "rdc_name": rdc_path.name,
        "returncode": int(completed.returncode),
        "output_folder_name": output_folder_name,
    }


def _log_payload_summary(payload: dict, artifact_package_path: Optional[Path]) -> None:
    print(f"report saved: {payload.get('_output_path', '')}")
    if artifact_package_path is not None:
        print(f"artifact package: {artifact_package_path}")

    artifacts = payload.get("artifacts", {})
    tokens = []
    if isinstance(artifacts, dict):
        material_info = artifacts.get("materials", {})
        texture_info = artifacts.get("textures", {})
        shader_info = artifacts.get("shaders", {})
        pass_info = artifacts.get("passes", {})
        if isinstance(material_info, dict) and material_info.get("index"):
            print(f"materials index: {material_info.get('index')}")
            if "count" in material_info:
                tokens.append(f"material_count={material_info.get('count', 0)}")
        if isinstance(texture_info, dict) and texture_info.get("index"):
            print(f"textures index: {texture_info.get('index')}")
            if "count" in texture_info:
                tokens.append(f"texture_count={texture_info.get('count', 0)}")
        if isinstance(shader_info, dict) and shader_info.get("index"):
            print(f"shaders index: {shader_info.get('index')}")
            if "count" in shader_info:
                tokens.append(f"shader_count={shader_info.get('count', 0)}")
        if isinstance(pass_info, dict) and pass_info.get("index"):
            print(f"passes index: {pass_info.get('index')}")
            if "count" in pass_info:
                tokens.append(f"pass_count={pass_info.get('count', 0)}")
    print("counts: " + ", ".join(tokens) if tokens else "counts: (empty)")


def _parse_single_rdc(rdc_path: Path, params, output_folder_name: Optional[str]) -> Path:
    output_root = _resolve_path("output")
    capture_folder = output_root if output_folder_name is None else output_root / output_folder_name
    cos_params = CosParams(str(rdc_path))
    artifact_root = _resolve_artifact_root(capture_folder, params, cos_params)
    artifact_package_path = _resolve_artifact_package_path(capture_folder, artifact_root, params)
    output_path = capture_folder / "rdc_entry.json"

    schema = "1"
    export_texture_assets = _to_bool(params.get("export_texture_assets"), default=False)
    material_output_dir = artifact_root / "rdc_material"
    source_output_dir = artifact_root
    texture_output_dir = artifact_root / "rdc_texture" if export_texture_assets else None
    shader_output_dir = None
    pass_output_dir = artifact_root / "rdc_pass"

    _reset_packaged_output(capture_folder, artifact_root, artifact_package_path)

    print(f"rdc_parse start: {rdc_path}")
    print(
        "rdc_parse options: "
        f"export_texture_assets={export_texture_assets}, "
        f"pkg={params.get('pkg', '') or '(none)'}"
    )

    payload = parse_capture_rdc(
        str(rdc_path),
        include_source=True,
        schema=schema,
        source_output_dir=str(source_output_dir) if source_output_dir is not None else None,
        material_output_dir=str(material_output_dir),
        texture_output_dir=str(texture_output_dir) if texture_output_dir is not None else None,
        shader_output_dir=str(shader_output_dir) if shader_output_dir is not None else None,
        pass_output_dir=str(pass_output_dir),
        export_texture_images=export_texture_assets,
    )
    cos_params_payload = cos_params.to_json_dict()
    _prefix_artifact_paths(payload, capture_folder, artifact_root)
    if artifact_package_path is not None:
        _create_artifact_zip(artifact_root, artifact_package_path)
        shutil.rmtree(artifact_root)
        cos_params_payload["package"] = artifact_package_path.name
    payload.pop("artifact_package", None)
    payload.pop("env_params", None)
    payload.pop("cos_params", None)
    artifacts = payload.get("artifacts", {})
    if isinstance(artifacts, dict):
        artifacts.pop("shaders", None)
    payload["cos_params"] = cos_params_payload

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    payload["_output_path"] = str(output_path)
    _log_payload_summary(payload, artifact_package_path)
    return output_path


@task_manager.manager.register
class ParseRdcTask:
    """Parse one .rdc and output material/shader JSON report."""

    TASK_ID = "rdc_parse"

    def execute(self, args, params):
        try:
            save_dir = _resolve_path(params.get("save_dir", cfg.save_dir))
            rdc_arg = params.get("rdc") or params.get("input") or params.get("file") or params.get("path")

            if rdc_arg:
                rdc_path = _resolve_path(rdc_arg, save_dir)
            else:
                rdc_path = _find_latest_rdc(save_dir)
                if rdc_path is None:
                    raise RuntimeError(f"no .rdc file found in {save_dir}")

            if not rdc_path.exists() or rdc_path.suffix.lower() != ".rdc":
                raise RuntimeError(f"invalid rdc file: {rdc_path}")
            output_folder_name = _resolve_output_folder_name(rdc_path, params)
            _parse_single_rdc(rdc_path, params, output_folder_name)

        except Exception as exc:
            print(f"rdc_parse_task error: {exc}")


@task_manager.manager.register
class ParseRdcTaskCompat(ParseRdcTask):
    """Compatibility alias for legacy task id parse_rdc."""

    TASK_ID = "parse_rdc"


@task_manager.manager.register
class ParseRdcBatchTask:
    """Parse all .rdc files in one directory."""

    TASK_ID = "rdc_parse_batch"

    def execute(self, args, params):
        try:
            dir_path = _resolve_path(params.get("dir", params.get("save_dir", cfg.save_dir)))
            rdc_files = _list_rdc_files(dir_path)
            if not rdc_files:
                raise RuntimeError(f"no .rdc files found in {dir_path}")

            output_value = params.get("output") or params.get("ouput")
            if output_value is None or not str(output_value).strip():
                params = dict(params)
                params["output"] = "name"

            workers = _to_int(params.get("workers"), default=1)
            if workers <= 1:
                print(f"rdc_parse_batch start: dir={dir_path}, count={len(rdc_files)}, workers=1")
                for index, rdc_path in enumerate(rdc_files, start=1):
                    print(f"rdc_parse_batch progress: {index}/{len(rdc_files)} -> {rdc_path.name}")
                    output_folder_name = _resolve_batch_output_folder_name(rdc_path, params)
                    _parse_single_rdc(rdc_path, params, output_folder_name)
                print(f"rdc_parse_batch done: count={len(rdc_files)}, workers=1")
                return

            print(f"rdc_parse_batch start: dir={dir_path}, count={len(rdc_files)}, workers={workers}")
            future_map = {}
            completed_count = 0
            failed_results = []

            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                for rdc_path in rdc_files:
                    output_folder_name = _resolve_batch_output_folder_name(rdc_path, params)
                    print(f"rdc_parse_batch submit: {rdc_path.name} -> output/{output_folder_name}")
                    future = executor.submit(_run_single_rdc_subprocess, rdc_path, dict(params), output_folder_name)
                    future_map[future] = rdc_path.name

                for future in concurrent.futures.as_completed(future_map):
                    result = future.result()
                    completed_count += 1
                    rdc_name = result.get("rdc_name", future_map[future])
                    returncode = int(result.get("returncode", 1))
                    if returncode == 0:
                        print(f"rdc_parse_batch progress: {completed_count}/{len(rdc_files)} done -> {rdc_name}")
                    else:
                        failed_results.append(result)
                        print(
                            "rdc_parse_batch progress: "
                            f"{completed_count}/{len(rdc_files)} failed -> {rdc_name}, returncode={returncode}"
                        )

            if failed_results:
                failed_names = ", ".join(str(item.get("rdc_name", "")) for item in failed_results)
                print(
                    f"rdc_parse_batch done: count={len(rdc_files)}, workers={workers}, "
                    f"failed={len(failed_results)} [{failed_names}]"
                )
            else:
                print(f"rdc_parse_batch done: count={len(rdc_files)}, workers={workers}")
        except Exception as exc:
            print(f"rdc_parse_batch_task error: {exc}")
