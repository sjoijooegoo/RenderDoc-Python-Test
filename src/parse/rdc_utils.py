from __future__ import annotations

from typing import Iterable, Iterator

import renderdoc as rd


def iter_actions(actions: Iterable[rd.ActionDescription]) -> Iterator[rd.ActionDescription]:
    for action in actions:
        yield action
        if action.children:
            for child in iter_actions(action.children):
                yield child


def list_all_actions(controller: rd.ReplayController):
    return list(iter_actions(controller.GetRootActions()))


def get_action_name(action: rd.ActionDescription, controller: rd.ReplayController) -> str:
    structured_file = controller.GetStructuredFile()
    try:
        return action.GetName(structured_file)
    except Exception:
        return action.customName if action.customName else ""


def is_draw_or_dispatch(action: rd.ActionDescription) -> bool:
    flags = action.flags
    return bool(
        flags
        & (
            rd.ActionFlags.Drawcall
            | rd.ActionFlags.Dispatch
            | rd.ActionFlags.MeshDispatch
            | rd.ActionFlags.DispatchRay
        )
    )
