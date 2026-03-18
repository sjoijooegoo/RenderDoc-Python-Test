from __future__ import annotations

import os
import platform
import time
from pathlib import Path
from typing import Optional

from common import cfg
from parse import rdc_utils, utils
from parse.capture_loader import load_capture

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


def _find_latest_rdc(save_dir: Path) -> Optional[Path]:
    if not save_dir.exists():
        return None
    files = sorted(save_dir.glob("*.rdc"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


@task_manager.manager.register
class RdcLoadTestTask:
    """Minimal diagnostics task: load capture only and print debug info."""

    TASK_ID = "rdc_load_test"

    def execute(self, args, params):
        cap = None
        controller = None
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

            print(f"[rdc_load_test] start: file={rdc_path}")
            print(
                "[rdc_load_test] env: "
                f"host={platform.node()}, platform={platform.platform()}, "
                f"python={platform.python_version()}, session={os.environ.get('SESSIONNAME', '')}"
            )
            print(
                "[rdc_load_test] capture: "
                f"name={rdc_path.name}, size={rdc_path.stat().st_size}"
            )

            start = time.perf_counter()
            cap, controller = load_capture(str(rdc_path))
            load_elapsed = time.perf_counter() - start
            print(f"[rdc_load_test] load ok: elapsed={load_elapsed:.2f}s")

            api_props = controller.GetAPIProperties()
            print(
                "[rdc_load_test] replay: "
                f"pipelineType={utils.enum_name(getattr(api_props, 'pipelineType', None))}, "
                f"vendor={utils.enum_name(getattr(api_props, 'vendor', None))}, "
                f"localRenderer={utils.enum_name(getattr(api_props, 'localRenderer', None))}, "
                f"remoteReplay={getattr(api_props, 'remoteReplay', False)}, "
                f"degraded={getattr(api_props, 'degraded', False)}"
            )

            resources = controller.GetResources() or []
            textures = controller.GetTextures() or []
            all_actions = rdc_utils.list_all_actions(controller)
            draw_actions = [action for action in all_actions if rdc_utils.is_draw_or_dispatch(action)]
            print(
                "[rdc_load_test] stats: "
                f"resources={len(resources)}, textures={len(textures)}, "
                f"actions={len(all_actions)}, draw_or_dispatch_actions={len(draw_actions)}"
            )

            if all_actions:
                first = all_actions[0]
                print(
                    "[rdc_load_test] first_action: "
                    f"event_id={getattr(first, 'eventId', 0)}, "
                    f"name={getattr(first, 'customName', '') or getattr(first, 'flags', '')}"
                )

            print("[rdc_load_test] done")
        except Exception as exc:
            print(f"rdc_load_test_task error: {exc}")
        finally:
            if controller is not None:
                try:
                    controller.Shutdown()
                except Exception:
                    pass
            if cap is not None:
                try:
                    cap.Shutdown()
                except Exception:
                    pass
