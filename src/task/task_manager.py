'''
author: v_sycisong
LastEditors: v_sycisong
'''
import argparse
from typing import Type, Dict
from common import cfg

class TaskManager:
    def __init__(self):
        self.parser = argparse.ArgumentParser(description="RenderDoc 自动化工具")
        self.subparsers = self.parser.add_subparsers(dest="task_name", help="可用任务")
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

    def execute_task(self):
        args, unknown = self.parser.parse_known_args()
        
        task_id = args.task_name
        
        if not task_id or task_id not in self.task_map:
            print(f"[*] 使用默认任务 {cfg.default_task_id}")
            task_id = cfg.default_task_id
            unknown = cfg.default_task_params.split()

        task = self.task_map[task_id]
        
        if task_id is not None:
            params = {}
            for item in unknown:
                if '=' in item:
                    k, v = item.split('=', 1)
                    params[k] = v  
            task.execute(args, params)
        else:
            self.parser.print_help()

manager = TaskManager()