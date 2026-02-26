'''
author: v_sycisong
LastEditors: v_sycisong
'''

from global_config import cfg
cfg.setup_python_env()

import renderdoc_task

if __name__ == "__main__":
    renderdoc_task.manager.execute_task()