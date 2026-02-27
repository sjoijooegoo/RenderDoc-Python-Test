'''
author: v_sycisong
LastEditors: v_sycisong
'''
import os
from datetime import datetime
import json
from . import task_manager
from common.command_type import CaptureFrameCommandType
from capture.remote_object import RemoteObject
from common.global_config import cfg
import socket
import json
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
    conn.sendall((json.dumps(payload) + "\n").encode("utf-8"))
    
    
@task_manager.manager.register
class TCPServerTask:
    TASK_ID = "server"
    def execute(self, args, params):
        listen_sock = init_server_socket()
        remote_object = RemoteObject(cfg.device_serial, cfg.android_exe_path, "adb")
        print("--- 正在运行，等待远程指令 ---")
        running = True
        try:
            conn, addr = listen_sock.accept()
            buffer = ""
            while running:
                try:
                    data = conn.recv(1024).decode('utf-8')
                    if not data:
                        print("客户端已断开连接")
                        break
                    buffer += data
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        if not line:
                            continue
                        try:
                            command_json = json.loads(line)
                            command = int(command_json.get("command"))
                            print(f"收到指令: {command}")
                        except json.JSONDecodeError:
                            print(f"JSON 解析失败: {line}")
                            continue

                        if command == CaptureFrameCommandType.Launch_RDC:
                            try:
                                remote_object.launch_renderdoc()
                            except Exception as e:
                                print(f"启动renderdoc出错: {e}")
                                send_response(conn, command, False, str(e))
                            send_response(conn, command, True)

                        elif command == CaptureFrameCommandType.Launch_APP:
                            try:
                                remote_object.launch_capture_app()
                            except Exception as e:
                                print(f"启动app出错: {e}")
                                send_response(conn, command, False, str(e))
                            send_response(conn, command, True)

                        elif command == CaptureFrameCommandType.APP_CAPTURE:
                            try:
                                remote_object.capture()
                            except Exception as e:
                                print(f"截帧出错: {e}")
                                send_response(conn, command, False, str(e))
                            send_response(conn,command, True)

                        elif command == CaptureFrameCommandType.SET_DIR:
                            new_path = command_json.get("new_path")
                            try:
                                os.makedirs(new_path, exist_ok=True)
                                cfg.rdc_save_dir = new_path
                            except Exception as e:
                                print(f"设置新路径出错: {e}")
                                send_response(conn, command, False,str(e))
                            send_response(conn, command, True)

                        elif command == CaptureFrameCommandType.SET_DEVICE_SERIAL:
                            device_serial = command_json.get("device_serial")
                            print(f"设置使用的设备序列号:{device_serial}")
                            send_response(conn, command, True)

                        elif command == CaptureFrameCommandType.CLOSE_CONNNET:
                            print("收到停止服务指令，正在退出...")
                            send_response(conn, command, True)
                            running = False

                        else:
                            send_response(conn, command,False, "Unknown command.")

                except Exception as e:
                    send_response(conn, command,False, str(e))
                    print(f"处理数据出错: {e}")

        except KeyboardInterrupt:
            print("停止服务")

        finally:
            try:
                conn.close()
            except Exception:
                pass
            listen_sock.close()
