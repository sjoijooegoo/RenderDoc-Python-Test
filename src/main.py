'''
author: v_sycisong
LastEditors: v_sycisong
'''

from common.global_config import cfg
cfg.setup_python_env()

import task

if __name__ == "__main__":
    task.manager.execute_task()