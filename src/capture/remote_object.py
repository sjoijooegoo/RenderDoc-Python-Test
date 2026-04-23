import os
import posixpath
import shlex
import subprocess
import threading
import time
from time import sleep

import renderdoc as rd


def ping_remote(remote, kill_event):
    success = True
    while success and not kill_event.is_set():
        try:
            success = remote.Ping()
        except Exception as e:
            print(f"[remote] ping failed: {e}")
            success = False
        sleep(1)


class RemoteObject:
    def __init__(self, device_serial, exe_path, protocol_to_use="adb", client_name="RemoteObject"):
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

    def _stop_app_ping(self):
        if self.app_kill_event is not None:
            self.app_kill_event.set()

        if self.app_ping_thread is not None:
            self.app_ping_thread.join(timeout=5)

        self.app_kill_event = None
        self.app_ping_thread = None

    def _start_app_ping(self):
        self._stop_app_ping()
        self.app_kill_event = threading.Event()
        self.app_ping_thread = threading.Thread(
            target=ping_remote,
            args=(self.remote_server, self.app_kill_event),
            daemon=True,
        )
        self.app_ping_thread.start()

    def _validate_launch_args(self):
        if not self.exe_path:
            raise ValueError("Android package/activity is empty")

        if self.protocol_to_use == "adb":
            if "/" not in self.exe_path:
                raise ValueError(
                    "Android launch target must be '<package>/<activity>', "
                    f"got {self.exe_path!r}"
                )

            package, activity = self.exe_path.split("/", 1)
            if not package or not activity:
                raise ValueError(
                    "Android package/activity must not be empty, "
                    f"got {self.exe_path!r}"
                )

    @staticmethod
    def _format_result(result):
        if result is None:
            return "None"
        try:
            return result.Message()
        except Exception:
            return str(result)

    @staticmethod
    def _result_ok(result):
        if result is None:
            return False
        try:
            return result.OK()
        except Exception:
            return bool(result)

    @staticmethod
    def _format_execute_result(exec_result):
        if exec_result is None:
            return "None"

        try:
            ident = exec_result.ident
        except Exception as e:
            ident = f"<failed to read ident: {e}>"

        try:
            result = RemoteObject._format_result(exec_result.result)
        except Exception as e:
            result = f"<failed to read result: {e}>"

        return f"ident={ident}, result={result}"

    def _debug_state(self, prefix):
        print(
            f"[remote] {prefix}: "
            f"protocol={self.protocol_to_use}, "
            f"device_serial={self.device_serial}, "
            f"device={self.device}, "
            f"url={self.url}, "
            f"exe_path={self.exe_path}, "
            f"working_dir={self.working_dir!r}, "
            f"cmd_line={self.cmd_line!r}, "
            f"env_count={len(self.env)}"
        )

    def _adb_shell(self, command):
        device = self.device or self.device_serial
        if not device:
            raise RuntimeError("ADB device is not selected")

        completed = subprocess.run(
            ["adb", "-s", device, "shell", command],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"adb shell failed: {command}\n"
                f"stdout={completed.stdout}\n"
                f"stderr={completed.stderr}"
            )

    @staticmethod
    def _normalise_remote_save_name(save_name):
        if save_name is None:
            return ""

        save_name = str(save_name)
        save_name = save_name.replace("\\", "/").strip()

        # Windows absolute paths are local paths, so only use their basename on device.
        if len(save_name) >= 3 and save_name[1] == ":" and save_name[2] == "/":
            save_name = posixpath.basename(save_name)

        while save_name.startswith("./"):
            save_name = save_name[2:]

        return save_name

    def _remote_capture_path_for_save_name(self, cap_path, save_name):
        save_name = self._normalise_remote_save_name(save_name)
        if not save_name:
            return cap_path

        if not save_name.endswith(".rdc"):
            save_name += ".rdc"

        if save_name.startswith("/sdcard/") or save_name.startswith("/storage/"):
            return save_name

        return posixpath.join(posixpath.dirname(cap_path), save_name)

    def _rename_remote_capture(self, cap_path, save_name):
        renamed_path = self._remote_capture_path_for_save_name(cap_path, save_name)
        if renamed_path == cap_path:
            return cap_path

        self._adb_shell(
            "mkdir -p "
            + shlex.quote(posixpath.dirname(renamed_path))
            + " && mv -f "
            + shlex.quote(cap_path)
            + " "
            + shlex.quote(renamed_path)
        )
        print(f"Remote capture renamed: {cap_path} -> {renamed_path}")
        return renamed_path

    def _create_target_control(self, ident):
        last_error = None
        max_attempts = 5
        for attempt in range(max_attempts):
            print(
                "[remote] CreateTargetControl args: "
                f"url={self.url}, ident={ident}, client_name={self.client_name}, "
                f"attempt={attempt + 1}/{max_attempts}"
            )
            try:
                target = rd.CreateTargetControl(self.url, ident, self.client_name, True)
            except OSError as e:
                last_error = e
                print(f"[remote] CreateTargetControl raised OSError: {e}")
            except Exception as e:
                last_error = e
                print(f"[remote] CreateTargetControl raised exception: {e}")
            else:
                if target is not None:
                    return target
                last_error = RuntimeError("CreateTargetControl returned None")
                print(f"[remote] {last_error}")

            sleep_seconds = 1.0 if attempt < max_attempts - 1 else 0
            if sleep_seconds > 0:
                sleep(sleep_seconds)

        raise RuntimeError(
            "Failed to create target control after app launch: "
            f"url={self.url}, ident={ident}, client_name={self.client_name}, "
            f"last_error={last_error}"
        )

    def launch_renderdoc(self):
        self._debug_state("launch_renderdoc begin")
        protocol = rd.GetDeviceProtocolController(self.protocol_to_use)
        if protocol is None:
            raise RuntimeError(f"device protocol is not available: {self.protocol_to_use}")

        devices = list(protocol.GetDevices())
        print(f"[remote] available {self.protocol_to_use} devices: {devices}")

        if self.device_serial and self.device_serial in devices:
            self.device = self.device_serial
            print(f"Using device: {self.device}")
        else:
            print(f"Device {self.device_serial} not found, using default device")
            if len(devices) == 0:
                raise RuntimeError(f"no {self.protocol_to_use} devices connected")
            self.device = devices[0]

        self.device_name = protocol.GetFriendlyName(f"{protocol.GetProtocolName()}://{self.device}")
        print(f"Running on {self.device} - named {self.device_name}")

        self.url = protocol.GetProtocolName() + "://" + self.device
        self.remote_server = None
        check_result = rd.CheckRemoteServerConnection(self.url)
        print(f"[remote] CheckRemoteServerConnection({self.url}): {self._format_result(check_result)}")
        start_result = None

        if not check_result.OK():
            start_result = protocol.StartRemoteServer(self.url)
            print(f"StartRemoteServer: {self._format_result(start_result)}")

        result = None
        max_attempts = 10
        for attempt in range(max_attempts):
            print(f"[remote] CreateRemoteServerConnection attempt {attempt + 1}/{max_attempts}: {self.url}")
            result, self.remote_server = rd.CreateRemoteServerConnection(self.url)
            print(
                "[remote] CreateRemoteServerConnection result: "
                f"{self._format_result(result)}, remote_server={self.remote_server}"
            )
            if self.remote_server is not None and result.OK():
                break
            sleep_seconds = 1.5 if attempt < max_attempts - 1 else 0
            if sleep_seconds > 0:
                sleep(sleep_seconds)

        if self.remote_server is None:
            raise RuntimeError(
                "Failed to connect remote server: "
                f"url={self.url}, "
                f"check={self._format_result(check_result)}, "
                f"start={self._format_result(start_result)}, "
                f"connect={self._format_result(result)}"
            )
        self._debug_state("launch_renderdoc done")

    def launch_capture_app(self):
        self._debug_state("launch_capture_app begin")
        self._validate_launch_args()
        self._stop_app_ping()
        self.app_target = None

        if self.remote_server is None:
            self.launch_renderdoc()
            if self.remote_server is None:
                return False

        print(
            "[remote] ExecuteAndInject args: "
            f"app={self.exe_path}, working_dir={self.working_dir!r}, "
            f"cmd_line={self.cmd_line!r}, env={self.env}"
        )
        try:
            exec_result = self.remote_server.ExecuteAndInject(
                self.exe_path,
                self.working_dir,
                self.cmd_line,
                self.env,
                self.opts,
            )
        except Exception as e:
            raise RuntimeError(
                "ExecuteAndInject raised an exception: "
                f"app={self.exe_path}, "
                f"working_dir={self.working_dir!r}, "
                f"cmd_line={self.cmd_line!r}, "
                f"env={self.env}, "
                f"url={self.url}, "
                f"device={self.device}"
            ) from e

        print(f"[remote] ExecuteAndInject result: {self._format_execute_result(exec_result)}")

        if exec_result is None:
            raise RuntimeError("ExecuteAndInject returned None")

        exec_details = exec_result.result
        if not self._result_ok(exec_details) or exec_result.ident == 0:
            raise RuntimeError(f"ExecuteAndInject failed: {self._format_execute_result(exec_result)}")

        try:
            self.app_target = self._create_target_control(exec_result.ident)
        except Exception as e:
            raise RuntimeError(
                "CreateTargetControl raised an exception: "
                f"url={self.url}, ident={exec_result.ident}, client_name={self.client_name}"
            ) from e

        if self.app_target is None:
            self.remote_server.ShutdownServerAndConnection()
            raise RuntimeError(f"Failed to create target control: {self._format_execute_result(exec_result)}")

        self._start_app_ping()
        self._debug_state("launch_capture_app done")
        return True

    def capture(self, frame_count=1, file_name="", save_dir=""):
        print(
            "[remote] capture begin: "
            f"frame_count={frame_count}, file_name={file_name!r}, save_dir={save_dir!r}"
        )
        if self.remote_server is None:
            raise RuntimeError("Remote server not started")

        if self.app_target is None:
            raise RuntimeError("Target control is not connected. Launch the app before capturing.")

        self.app_target.TriggerCapture(frame_count)
        print("Capture started")

        msg = None
        start_time = time.perf_counter()
        while msg is None or msg.type != rd.TargetControlMessageType.NewCapture:
            msg = self.app_target.ReceiveMessage(None)
            if time.perf_counter() - start_time > 30:
                raise TimeoutError("Timeout waiting for capture callback")

        cap_path = msg.newCapture.path
        print(f"Remote capture path: {cap_path}")

        if file_name:
            cap_path = self._rename_remote_capture(cap_path, file_name)

        if save_dir == "":
            # Not saving locally.
            print("[remote] save_dir is empty; capture remains on remote device")
            return cap_path

        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        if file_name == "":
            file_name = os.path.basename(cap_path)

        if not file_name.endswith(".rdc"):
            file_name += ".rdc"

        file_path = os.path.join(save_dir, file_name)
        file_dir = os.path.dirname(file_path)
        if file_dir:
            os.makedirs(file_dir, exist_ok=True)
        self.remote_server.CopyCaptureFromRemote(cap_path, file_path, None)
        print(f"Saved to: {file_path}")
        return cap_path
