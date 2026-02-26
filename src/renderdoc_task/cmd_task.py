'''
author: v_sycisong
LastEditors: v_sycisong
'''
import os
from datetime import datetime
from . import task_manager
from remote_object import RemoteObject
from global_config import cfg

@task_manager.manager.register
class CMDTask:
    IS_DEFAULT = True
    TASK_ID = "cmd"
    def execute(self, args, params):
        print("\n" + "=" * 35)
        print("------------ 控制台测试 -----------")
        print("可用命令: ")
        print("  rdc		- 启动 RenderDoc")
        print("  app		- 启动 目标App")
        print("  cap		- 截帧 参数1(文件名)")
        print("  exit		- 停止并退出")
        print("=" * 35 + "\n")
        remote_object = RemoteObject()
        while True:
            user_input = input(">> ").strip().lower().split()
            if not user_input:
                continue

            cmd = user_input[0]

            if cmd == "rdc":
                success = remote_object.launch_renderdoc()
                print(f"[*] 启动 RenderDoc: {'成功' if success else '失败'}")

            elif cmd == "app":
                success = remote_object.launch_capture_app()
                print(f"[*] 启动 App: {'成功' if success else '失败'}")

            elif cmd == "cap":
                save_name = user_input[1] if len(user_input) > 1 else f"Cap_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                if not save_name.endswith(".rdc"):
                    save_name += ".rdc"
                print(f"[*] 正在截帧至: {save_name} ...")
                success = remote_object.capture(save_name)
                print(f"[*] 截帧结果: {'成功' if success else '失败'}")
                
            elif cmd == "exit":
                print("[!] 正在退出控制台模式...")
                break
            else:
                print(f"[?] 未知命令: {cmd}")