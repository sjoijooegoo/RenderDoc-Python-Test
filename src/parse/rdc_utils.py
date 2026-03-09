from __future__ import annotations

from typing import Iterable, Iterator, List

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
        name = action.GetName(structured_file)
        if name:
            return name
    except Exception:
        pass
    return action.customName if action.customName else ""


def _is_marker_action(action: rd.ActionDescription) -> bool:
    flags = action.flags
    return bool(flags & (rd.ActionFlags.PushMarker | rd.ActionFlags.SetMarker))


def get_marker_path(action: rd.ActionDescription, controller: rd.ReplayController) -> str:
    markers: List[str] = []
    node = action.parent
    while node is not None:
        if _is_marker_action(node):
            name = get_action_name(node, controller).strip()
            if name:
                markers.append(name)
        node = node.parent

    markers.reverse()

    if _is_marker_action(action):
        name = get_action_name(action, controller).strip()
        if name:
            markers.append(name)

    return "/".join(markers)


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
