'''
author: v_sycisong
LastEditors: v_sycisong
'''
from . import task_manager
from capture import RemoteObject
from common import cfg


@task_manager.manager.register
class CMDTask:
    TASK_ID = "cmd"

    def execute(self, args, params):
        print("\n" + "=" * 35)
        print("------------ 控制台测试 -----------")
        print("可用命令:")
        print("  rdc        - 启动 RenderDoc")
        print("  app        - 启动目标 App")
        print("  cap [name] - 截帧，name 可选")
        print("  exit       - 退出控制台")
        print("=" * 35 + "\n")

        remote_object = RemoteObject(cfg.device_serial, cfg.android_exe_path, "adb")

        while True:
            user_input = input(">> ").strip().split()
            if not user_input:
                continue

            cmd = user_input[0].lower()

            if cmd == "rdc":
                try:
                    remote_object.launch_renderdoc()
                    print("[*] 启动 RenderDoc: 成功")
                except Exception as e:
                    print(f"[*] 启动 RenderDoc: 失败 - {e}")

            elif cmd == "app":
                try:
                    remote_object.launch_capture_app()
                    print("[*] 启动 App: 成功")
                except Exception as e:
                    print(f"[*] 启动 App: 失败 - {e}")

            elif cmd == "cap":
                try:
                    # Keep RenderDoc remote naming format when name is omitted,
                    # e.g. com.tencent.mho_2026.03.04_10.23_frame1303.rdc
                    save_name = user_input[1] if len(user_input) > 1 else ""
                    display_name = save_name if save_name else "(remote default name)"
                    print(f"[*] 正在截帧至 {display_name} ...")
                    remote_object.capture(1, save_name, cfg.save_dir)
                    print("[*] 截帧结果: 成功")
                except Exception as e:
                    print(f"[*] 截帧: 失败 - {e}")

            elif cmd == "exit":
                print("[!] 正在退出控制台模式...")
                break

            else:
                print(f"[?] 未知命令: {cmd}")
