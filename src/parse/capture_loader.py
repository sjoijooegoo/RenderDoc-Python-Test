from __future__ import annotations

from typing import Tuple

import renderdoc as rd


def load_capture(filename: str) -> Tuple[rd.CaptureFile, rd.ReplayController]:
    cap = rd.OpenCaptureFile()

    result = cap.OpenFile(filename, "", None)
    if result != rd.ResultCode.Succeeded:
        raise RuntimeError(f"Could not open capture file: {result}")

    if not cap.LocalReplaySupport():
        raise RuntimeError("Capture cannot be replayed locally")

    result, controller = cap.OpenCapture(rd.ReplayOptions(), None)
    if result != rd.ResultCode.Succeeded:
        raise RuntimeError(f"Could not initialize replay: {result}")

    return cap, controller


# Backward-compatible alias for existing callers.
def loadCapture(filename: str):
    return load_capture(filename)
