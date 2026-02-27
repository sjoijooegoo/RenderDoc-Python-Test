'''
author: v_sycisong
LastEditors: v_sycisong
'''
import argparse
from typing import Type, Dict

class TaskManager:
    def __init__(self):
        self.parser = argparse.ArgumentParser(description="RenderDoc 自动化工具")
        self.subparsers = self.parser.add_subparsers(dest="task_name", help="可用任务")
        self.task_map: Dict[str, object] = {}
        self.default_task_id = None

    def register(self, cls: Type):
        task_id = getattr(cls, "TASK_ID", None)
        if not task_id:
            return cls

        is_default = getattr(cls, "IS_DEFAULT", False)
        if is_default:
            self.default_task_id = task_id

        instance = cls()
        self.task_map[task_id] = instance

        sub_parser = self.subparsers.add_parser(task_id, help=cls.__doc__ or f"Run {task_id}")
        if hasattr(instance, "add_arguments"):
            instance.add_arguments(sub_parser)
            
        return cls

    def execute_task(self):
        args, unknown = self.parser.parse_known_args()
        
        task_id = args.task_name or self.default_task_id
        
        if not task_id or task_id not in self.task_map:
            self.parser.print_help()
            return

        task = self.task_map[task_id]
        if args.task_name is None:
            print(f"[*] 自动匹配默认任务: {task_id}")
        
        params = {}
        for item in unknown:
            if '=' in item:
                k, v = item.split('=', 1)
                params[k] = v
        
        task.execute(args, params)

manager = TaskManager()