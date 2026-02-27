import socket
import json
import threading
import os
from time import sleep
import time

import renderdoc as rd


def ping_remote(remote, kill_event):
    success = True
    while success and not kill_event.is_set():
        success = remote.Ping()
        sleep(1)


class RemoteObject:
    def __init__(self, device_serial, exe_path, protocol_to_use = "adb", client_name = "remote_object"):

        self.url = ""
        self.protocol_to_use = protocol_to_use
        self.device = None
        self.device_name = None
        self.remote_server = None

        self.opts = rd.CaptureOptions()
        self.opts.allowVSync = True
        self.opts.allowFullscreen = True
        self.opts.apiValidation = False
        self.opts.captureCallstacks = False
        self.opts.refAllResources = True
        self.opts.captureAllCmdLists = False
        self.exe_path = exe_path
        self.working_dir = ""
        self.cmd_line = ""
        self.env = []
        self.client_name = client_name
        self.device_serial = device_serial
        
        self.app_target = None
        self.app_kill_event = None
        self.app_ping_thread = None


    def launch_renderdoc(self):
        protocol = rd.GetDeviceProtocolController(self.protocol_to_use)

        devices = protocol.GetDevices()

        if self.device_serial in devices:
            self.device = devices[self.device_serial]
            print(f"使用设备: {self.device_serial}")
        else:
            print(f"设备 {self.device_serial} 未找到，使用默认设备")
            if len(devices) == 0:
                raise RuntimeError(f"no {self.protocol_to_use} devices connected")

            self.device = devices[0]

        self.device_name = protocol.GetFriendlyName(self.device)

        print(f"Running on {self.device} - named {self.device_name}")

        self.url = protocol.GetProtocolName() + "://" + self.device

        rd.CheckRemoteServerConnection(self.url)

        result, self.remote_server = rd.CreateRemoteServerConnection(self.url)

        if result == rd.ResultCode.NetworkIOFailed:
            protocol.StartRemoteServer(self.url)
            sleep(5)
            result, self.remote_server = rd.CreateRemoteServerConnection(self.url)

        if self.remote_server is None:
            raise RuntimeError(f"无法建立远程服务器连接: {result}")

    def launch_capture_app(self) :

        if self.remote_server is None:
            self.launch_renderdoc()
            if self.remote_server is None:
                return False

        exec_result = self.remote_server.ExecuteAndInject(self.exe_path, self.working_dir, self.cmd_line, self.env, self.opts)
        self.app_kill_event = threading.Event()
        self.app_ping_thread = threading.Thread(target=ping_remote, args=(self.remote_server, self.app_kill_event))
        self.app_ping_thread.daemon = True
        self.app_ping_thread.start()
        self.app_target  = rd.CreateTargetControl(self.url, exec_result.ident, self.client_name, True)

        if self.app_target  is None:
            self.app_kill_event.set()
            self.app_ping_thread.join()
            self.remote_server.ShutdownServerAndConnection()
            raise RuntimeError(f"无法启动远程应用")

    def capture(self, frame_count = 1, file_name = "",  save_dir = ""):

        if self.remote_server is None:
            print("未启动远程应用")
            return False

        self.app_target.TriggerCapture(frame_count)
        print("开始截帧")
        msg = None
        start_time = time.perf_counter()
        while msg is None or msg.type != rd.TargetControlMessageType.NewCapture:
            msg = self.app_target.ReceiveMessage(None)
            if time.perf_counter() - start_time > 30:
                print("超时：未收到截帧反馈")
                return False

        cap_path = msg.newCapture.path
        print(f"远程文件路径: {cap_path}")

        if save_dir == "" or file_name == "":
            #不保存至本地
            return
        
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        file_path = os.path.join(save_dir, file_name)
        
        self.remote_server.CopyCaptureFromRemote(cap_path, file_path, None)
        print(f"已保存至: {file_path}")