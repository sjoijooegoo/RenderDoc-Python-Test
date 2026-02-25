'''
author: v_sycisong
LastEditors: v_sycisong
'''
import os
import sys
import ctypes
import configparser

class GlobalConfig:
    def __init__(self):
        if getattr(sys, 'frozen', False):
            self.current_dir = os.path.dirname(os.path.dirname(sys.executable))
        else:
            self.current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        config_path = os.path.join(self.current_dir, 'config.ini')
        self.config = configparser.ConfigParser()

        if os.path.exists(config_path):
            self.config.read(config_path, encoding='utf-8')
        else:
            print(f"Warning: config.ini not found at {config_path}, using defaults.")


        self.device_serial = self.get_config('Android', 'serial', '')
        
        platform_map = {
            "win32": "windows",
            "linux": "linux",
            "darwin": "macos"
        }
        platform_dir = platform_map.get(sys.platform, sys.platform)

        self.renderdoc_lib_path = os.path.join(
            self.current_dir, 
            "lib", 
            platform_dir
        )

        #Network
        self.bind_port = int(self.get_config('Network', 'listen_port', '16688'))
        self.bind_ip = self.get_config('Network', 'listen_host', '0.0.0.0')
        #Adnroid
        self.android_package_name = self.get_config('Android', 'package_name', 'com.tencent.mho')
        self.android_activity_name = self.get_config('Android', 'activity_name', 'com.epicgames.unreal.SplashActivity')
        self.android_exe_path = self.android_exe_path = f"{self.android_package_name}/{self.android_activity_name}"
        #save
        self.rdc_save_dir = self.get_config('path', 'save_dir_abs', os.path.join(self.current_dir, "save"))
        print (f"rdc_save_dir: {self.rdc_save_dir}")


    def get_config(self, section, key, default):
        try:
            return self.config.get(section, key) or default
        except:
            return default

    def setup_python_env(self):
        print (f"{self.renderdoc_lib_path}")
        if self.renderdoc_lib_path not in sys.path:
            sys.path.append(self.renderdoc_lib_path)
        ctypes.CDLL(self.renderdoc_lib_path)
        if hasattr(os, 'add_dll_directory'):
            os.add_dll_directory(self.current_dir)
            os.add_dll_directory(self.renderdoc_lib_path)
        else:
            os.environ["PATH"] = self.renderdoc_lib_path + self.current_dir + os.pathsep + os.environ["PATH"]



cfg = GlobalConfig()