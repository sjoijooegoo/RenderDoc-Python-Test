'''
author: v_sycisong
LastEditors: v_sycisong
'''
import argparse
from typing import Dict, List, Type

from common import cfg


def emit_error_output(error) -> None:
    error_msg = str(error).replace("\r", " ").replace("\n", " ").replace(" ", "_")
    print(f"::set-output name=error_msg::{error_msg}", flush=True)


class TaskManager:
    def __init__(self):
        self.parser = argparse.ArgumentParser(description="RenderDoc automation tool")
        self.subparsers = self.parser.add_subparsers(dest="task_name", help="available tasks")
        self.task_map: Dict[str, object] = {}

    def register(self, cls: Type):
        task_id = getattr(cls, "TASK_ID", None)
        if not task_id:
            return cls

        instance = cls()
        self.task_map[task_id] = instance

        sub_parser = self.subparsers.add_parser(task_id, help=cls.__doc__ or f"Run {task_id}")
        if hasattr(instance, "add_arguments"):
            instance.add_arguments(sub_parser)

        return cls

    def _build_params(self, unknown) -> Dict[str, str]:
        params: Dict[str, str] = {}
        for item in unknown:
            if "=" in item:
                key, value = item.split("=", 1)
                params[key] = value
        return params

    def _parse_task_list(self, value: str) -> List[str]:
        if not value:
            return []
        return [item.strip() for item in str(value).split(",") if item.strip()]

    def _execute_registered_task(self, task_id: str, args, params: Dict[str, str]) -> None:
        task = self.task_map.get(task_id)
        if task is None:
            print(f"[task_manager] skip unknown task: {task_id}")
            return
        try:
            task.execute(args, params)
        except Exception as exc:
            emit_error_output(exc)
            raise

    def _run_hook_tasks(
        self,
        hook_name: str,
        task_names: List[str],
        current_task_id: str,
        args,
        params: Dict[str, str],
    ) -> None:
        for hook_task_id in task_names:
            if hook_task_id == current_task_id:
                print(f"[task_manager] skip {hook_name}: {hook_task_id} (same as current task)")
                continue
            print(f"[task_manager] {hook_name} start: {hook_task_id}")
            self._execute_registered_task(hook_task_id, args, params)
            print(f"[task_manager] {hook_name} done: {hook_task_id}")

    def execute_task(self):
        args, unknown = self.parser.parse_known_args()

        task_id = args.task_name

        if not task_id or task_id not in self.task_map:
            print(f"[*] use default task {cfg.default_task_id}")
            task_id = cfg.default_task_id
            unknown = cfg.default_task_params.split()

        if task_id is not None:
            params = self._build_params(unknown)
            hook_params = dict(params)
            hook_params.pop("pre_task", None)
            hook_params.pop("post_task", None)

            pre_tasks = self._parse_task_list(params.get("pre_task", ""))
            post_tasks = self._parse_task_list(params.get("post_task", ""))

            self._run_hook_tasks("pre_task", pre_tasks, task_id, args, hook_params)
            self._execute_registered_task(task_id, args, hook_params)
            self._run_hook_tasks("post_task", post_tasks, task_id, args, hook_params)
        else:
            self.parser.print_help()


manager = TaskManager()
