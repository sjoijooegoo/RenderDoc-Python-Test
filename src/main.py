import os
import json
import argparse

from global_config import cfg
from datetime import datetime

cfg.setup_python_env()

import renderdoc as rd
import socket_utils
from command_type import CommandType
from remote_object import RemoteObject


def start_tcp_server(remote_object: RemoteObject):
	listen_sock = socket_utils.init_server_socket()
	print("--- 正在运行，等待远程指令 ---")
	running = True
	try:
		while running:
			conn, addr = listen_sock.accept()

			with conn:
				try:
					data = conn.recv(1024).decode('utf-8')
					if not data: continue

					command_json = json.loads(data)
					command = int(command_json.get("command"))
					print(f"收到指令: {command}")

					if command == CommandType.Launch_RDC:
						try:
							remote_object.launch_renderdoc()
						except Exception as e:
							print(f"启动renderdoc出错: {e}")
							socket_utils.send_response(conn, command, False, str(e))
						socket_utils.send_response(conn, command, True)

					elif command == CommandType.Launch_APP:
						try:
							remote_object.launch_capture_app()
						except Exception as e:
							print(f"启动app出错: {e}")
							socket_utils.send_response(conn, command, False, str(e))
						socket_utils.send_response(conn, command, True)

					elif command == CommandType.APP_CAPTURE:
						time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
						save_name = command_json.get("save_name", f"Cap_{time_str}") + ".rdc"
						if not save_name.endswith(".rdc"):
							save_name += ".rdc"
						try:
							remote_object.capture(save_name)
						except Exception as e:
							print(f"截帧出错: {e}")
							socket_utils.send_response(conn, command, False, str(e))
						socket_utils.send_response(conn,command, True)

					elif command == CommandType.SET_DIR:
						new_path = command_json.get("new_path")
						try:
							os.makedirs(new_path, exist_ok=True)
							cfg.rdc_save_dir = new_path
						except Exception as e:
							print(f"设置新路径出错: {e}")
							socket_utils.send_response(conn, command, False,str(e))
						socket_utils.send_response(conn, command, True)

					elif command == CommandType.SET_DEVICE_SERIAL:
						device_serial = command_json.get("device_serial")
						print(f"设置使用的设备序列号:{device_serial}")
						socket_utils.send_response(conn, command, True)

					elif command == CommandType.CLOSE_CONNNET:
						print("收到停止服务指令，正在退出...")
						socket_utils.send_response(conn, command, True)
						running = False

					else:
						socket_utils.send_response(conn, command,False, "Unknown command.")

				except Exception as e:
					socket_utils.send_response(conn, command,False, str(e))
					print(f"处理数据出错: {e}")

	except KeyboardInterrupt:
		print("停止服务")

	finally:
		listen_sock.close()


def start_cmd(remote_object: RemoteObject):
	print("\n" + "=" * 35)
	print("--- 控制台交互模式 ---")
	print("可用命令: ")
	print("  rdc		- 启动 RenderDoc")
	print("  app		- 启动 目标App")
	print("  cap		- 截帧 参数1(文件名)")
	print("  setdir	- 设置保存路径 参数1(绝对路径)")
	print("  exit		- 停止并退出")
	print("=" * 35 + "\n")

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

		elif cmd == "setdir":
			if len(user_input) < 2:
				print("[!] 缺少路径参数")
				continue
			new_path = os.path.abspath(user_input[1])
			try:
				os.makedirs(new_path, exist_ok=True)
				cfg.rdc_save_dir = new_path
				print(f"[*] 设置保存路径: 成功 -> {new_path}")
			except Exception as e:
				print(f"[!] 设置保存路径失败: {e}")
		elif cmd == "exit":
			print("[!] 正在退出控制台模式...")
			break
		else:
			print(f"[?] 未知命令: {cmd}")

if __name__ == "__main__":

	parser = argparse.ArgumentParser(description="RenderDoc 自动化工具")

	parser.add_argument(
		"--server",
		action="store_true",
		help="TCP Server模式"
	)

	args = parser.parse_args()

	remote_object = RemoteObject()

	if args.server:
		start_tcp_server(remote_object)
	else:
		start_cmd(remote_object)
