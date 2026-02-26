'''
author: v_sycisong
LastEditors: v_sycisong
'''
import os

from . import task_manager
from global_config import cfg
import renderdoc as rd


@task_manager.manager.register
class ParseRdcTask:
    TASK_ID = "parse_rdc"
    
    def execute(self, args, params):
        try:
            file_path = params.get('path')
            print(f"parse_rdc_task: {file_path}")
            rd.InitialiseReplay(rd.GlobalEnvironment(), [])
            cap = rd.OpenCaptureFile()
            if cap.OpenFile(file_path, '', None) != rd.ResultCode.Succeeded:
                raise Exception(f"无法打开文件: {file_path}")
            if not cap.LocalReplaySupport():
                raise Exception(f"文件不支持本地回放: {file_path}")
            result, controller = cap.OpenCapture(rd.ReplayOptions(), None)
            if result != rd.ResultCode.Succeeded:
                raise Exception(f"回放初始化失败: {file_path}")
            print("%d top-level actions" % len(controller.GetRootActions()))
        except Exception as e:
            print(f"parse_rdc_task: {e}")   