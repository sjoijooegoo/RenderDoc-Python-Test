import socket
import json
import sys
from global_config import cfg


def init_server_socket():

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_socket.bind((cfg.bind_ip, cfg.bind_port))
        server_socket.listen(1)
        print(f"TCP Server模式启动已就绪: {cfg.bind_ip}:{cfg.bind_port}")
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