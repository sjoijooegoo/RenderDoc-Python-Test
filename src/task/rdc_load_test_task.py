from __future__ import annotations

import os
import platform
import time
from pathlib import Path
from typing import Optional

import renderdoc as rd

from common import cfg
from parse import rdc_utils, utils

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
        print(f"[rdc_load_test] start: params={params}")
        try:
            task_start = time.perf_counter()

            def step_call(name: str, fn, default=None):
                print(f"[rdc_load_test] step start: {name}")
                begin = time.perf_counter()
                try:
                    value = fn()
                    print(f"[rdc_load_test] step done: {name}, elapsed={time.perf_counter() - begin:.3f}s")
                    return value
                except Exception as exc:
                    print(
                        "[rdc_load_test] step error: "
                        f"{name}, elapsed={time.perf_counter() - begin:.3f}s, error={exc}"
                    )
                    return default

            save_dir = step_call("ResolveSaveDir", lambda: _resolve_path(params.get("save_dir", cfg.save_dir)))
            if save_dir is None:
                print("[rdc_load_test] abort: save_dir is unavailable")
                return

            rdc_arg = step_call("ReadRdcArg", lambda: params.get("rdc") or params.get("input") or params.get("file") or params.get("path"), "")
            if rdc_arg:
                rdc_path = step_call("ResolveRdcPath", lambda: _resolve_path(rdc_arg, save_dir))
            else:
                rdc_path = step_call("FindLatestRdc", lambda: _find_latest_rdc(save_dir))
                if rdc_path is None:
                    print(f"[rdc_load_test] abort: no .rdc file found in {save_dir}")
                    return

            valid_rdc = step_call(
                "ValidateRdcFile",
                lambda: bool(rdc_path.exists() and rdc_path.suffix.lower() == ".rdc"),
                False,
            )
            if not valid_rdc:
                print(f"[rdc_load_test] abort: invalid rdc file: {rdc_path}")
                return

            print(f"[rdc_load_test] start: file={rdc_path}")
            print(
                "[rdc_load_test] env: "
                f"host={platform.node()}, platform={platform.platform()}, "
                f"python={platform.python_version()}, session={os.environ.get('SESSIONNAME', '')}"
            )

            capture_size = step_call("GetCaptureSize", lambda: rdc_path.stat().st_size, 0)
            print(f"[rdc_load_test] capture: name={rdc_path.name}, size={capture_size}")

            probe_actions = step_call(
                "ParseProbeActions",
                lambda: int(str(params.get("probe_actions", "0") or "0")),
                0,
            )
            if probe_actions is None:
                probe_actions = 0
            if probe_actions < 0:
                probe_actions = 0

            cap = step_call("OpenCaptureFile", lambda: rd.OpenCaptureFile())
            if cap is None:
                print("[rdc_load_test] abort: OpenCaptureFile failed")
                return

            open_file_result = step_call("OpenFile", lambda: cap.OpenFile(str(rdc_path), "", None))
            print(f"[rdc_load_test] OpenFile result: {open_file_result}")
            if open_file_result != rd.ResultCode.Succeeded:
                print(f"[rdc_load_test] abort: Could not open capture file: {open_file_result}")
                return

            local_replay_supported = step_call("LocalReplaySupport", lambda: cap.LocalReplaySupport(), False)
            print(f"[rdc_load_test] LocalReplaySupport: {local_replay_supported}")
            if not local_replay_supported:
                print("[rdc_load_test] abort: Capture cannot be replayed locally")
                return

            open_capture_result = step_call("OpenCapture", lambda: cap.OpenCapture(rd.ReplayOptions(), None), (None, None))
            result = None
            if isinstance(open_capture_result, tuple) and len(open_capture_result) == 2:
                result, controller = open_capture_result
            print(f"[rdc_load_test] OpenCapture result: {result}")
            if result != rd.ResultCode.Succeeded or controller is None:
                print(f"[rdc_load_test] abort: Could not initialize replay: {result}")
                return

            api_props = step_call("GetAPIProperties", lambda: controller.GetAPIProperties())
            if api_props is not None:
                print(
                    "[rdc_load_test] replay: "
                    f"pipelineType={utils.enum_name(getattr(api_props, 'pipelineType', None))}, "
                    f"vendor={utils.enum_name(getattr(api_props, 'vendor', None))}, "
                    f"localRenderer={utils.enum_name(getattr(api_props, 'localRenderer', None))}, "
                    f"remoteReplay={getattr(api_props, 'remoteReplay', False)}, "
                    f"degraded={getattr(api_props, 'degraded', False)}"
                )

            resources = step_call("GetResources", lambda: controller.GetResources() or [], [])
            textures = step_call("GetTextures", lambda: controller.GetTextures() or [], [])
            all_actions = step_call("ListAllActions", lambda: rdc_utils.list_all_actions(controller), [])
            draw_actions = step_call(
                "FilterDrawOrDispatchActions",
                lambda: [action for action in all_actions if rdc_utils.is_draw_or_dispatch(action)],
                [],
            )

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

            if probe_actions > 0 and draw_actions:
                probe_count = min(probe_actions, len(draw_actions))
                print(f"[rdc_load_test] probe_actions start: count={probe_count}")
                for index, action in enumerate(draw_actions[:probe_count], start=1):
                    action_begin = time.perf_counter()
                    try:
                        set_begin = time.perf_counter()
                        controller.SetFrameEvent(action.eventId, True)
                        set_event_elapsed = time.perf_counter() - set_begin
                    except Exception as exc:
                        set_event_elapsed = -1.0
                        print(f"[rdc_load_test] probe step error: SetFrameEvent event_id={action.eventId}, error={exc}")

                    try:
                        get_begin = time.perf_counter()
                        _state = controller.GetPipelineState()
                        get_state_elapsed = time.perf_counter() - get_begin
                    except Exception as exc:
                        get_state_elapsed = -1.0
                        print(f"[rdc_load_test] probe step error: GetPipelineState event_id={action.eventId}, error={exc}")

                    action_elapsed = time.perf_counter() - action_begin
                    marker_name = getattr(action, "customName", "") or ""
                    print(
                        "[rdc_load_test] probe: "
                        f"{index}/{probe_count}, event_id={action.eventId}, "
                        f"set_event={set_event_elapsed:.3f}s, get_state={get_state_elapsed:.3f}s, "
                        f"total={action_elapsed:.3f}s, marker={marker_name}"
                    )
                print("[rdc_load_test] probe_actions done")

            print(f"[rdc_load_test] done: total_elapsed={time.perf_counter() - task_start:.3f}s")
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
