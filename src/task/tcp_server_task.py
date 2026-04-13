'''
author: v_sycisong
LastEditors: v_sycisong
'''
import os
import json
import traceback
from . import task_manager
from common import CaptureFrameCommandType,cfg
from capture import RemoteObject
import socket
import sys


def init_server_socket():

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_socket.bind((cfg.bind_ip, cfg.bind_port))
        server_socket.listen(1)
        print(f"TCP Server模式: {cfg.bind_ip}:{cfg.bind_port}")
        return server_socket
    except Exception as e:
        print(f"无法启动 Socket 服务: {e}")
        sys.exit(1)


def send_response(conn, command:int, success: bool, msg: str = ""):
    payload = {
        "command": command,
        "success": success,
        "msg": msg
    }
    print(f"[tcp] response: {payload}")
    conn.sendall((json.dumps(payload) + "\n").encode("utf-8"))


def send_exception_response(conn, command: int, action_name: str, error: Exception):
    stack = traceback.format_exc()
    print(f"[tcp] {action_name} failed: {error}")
    print(stack)
    send_response(conn, command, False, f"{action_name} failed: {error}\n{stack}")


def run_command(conn, command: int, action_name: str, action):
    print(f"[tcp] {action_name} start")
    try:
        result = action()
        if result is False:
            raise RuntimeError(f"{action_name} returned False")
    except Exception as e:
        send_exception_response(conn, command, action_name, e)
        return False

    print(f"[tcp] {action_name} done")
    send_response(conn, command, True)
    return True
    
    
@task_manager.manager.register
class TCPServerTask:
    TASK_ID = "server"
    def execute(self, args, params):
        listen_sock = init_server_socket()
        remote_object = RemoteObject(cfg.device_serial, cfg.android_exe_path, "adb")
        print("--- 正在运行，等待远程指令 ---")
        running = True
        try:
            while running:
                conn, addr = listen_sock.accept()

                with conn:
                    command = -1
                    try:
                        print(f"[tcp] accepted connection from {addr}")
                        data = conn.recv(1024).decode('utf-8')
                        if not data: continue
                        print(f"[tcp] raw request: {data!r}")
                        try:
                            command_json = json.loads(data)
                            command = int(command_json.get("command"))
                            print(f"收到指令: {command}, payload: {command_json}")
                        except json.JSONDecodeError:
                            print(f"JSON 解析失败: {data}")
                            send_response(conn, command, False, f"JSON parse failed: {data}")
                            continue
                        except Exception as e:
                            send_exception_response(conn, command, "parse command", e)
                            continue

                        if command == CaptureFrameCommandType.Launch_RDC:
                            run_command(conn, command, "launch RenderDoc", remote_object.launch_renderdoc)

                        elif command == CaptureFrameCommandType.Launch_APP:
                            run_command(conn, command, "launch app", remote_object.launch_capture_app)

                        elif command == CaptureFrameCommandType.APP_CAPTURE:
                            run_command(conn, command, "capture app frame", lambda: remote_object.capture(save_dir=cfg.save_dir))

                        elif command == CaptureFrameCommandType.SET_DIR:
                            new_path = command_json.get("new_path")
                            def set_dir():
                                if not new_path:
                                    raise ValueError("new_path is required")
                                os.makedirs(new_path, exist_ok=True)
                                cfg.save_dir = new_path
                                print(f"[tcp] save_dir updated: {cfg.save_dir}")

                            run_command(conn, command, "set save dir", set_dir)

                        elif command == CaptureFrameCommandType.SET_DEVICE_SERIAL:
                            device_serial = command_json.get("device_serial")
                            def set_device_serial():
                                if not device_serial:
                                    raise ValueError("device_serial is required")
                                cfg.device_serial = device_serial
                                remote_object.device_serial = device_serial
                                remote_object.remote_server = None
                                remote_object.app_target = None
                                print(f"[tcp] device serial updated: {device_serial}")

                            run_command(conn, command, "set device serial", set_device_serial)

                        elif command == CaptureFrameCommandType.CLOSE_CONNNET:
                            print("收到停止服务指令，正在退出...")
                            send_response(conn, command, True)
                            running = False

                        else:
                            send_response(conn, command,False, "Unknown command.")

                    except Exception as e:
                        send_exception_response(conn, command, "handle request", e)

        except KeyboardInterrupt:
            print("停止服务")

        finally:
            listen_sock.close()
