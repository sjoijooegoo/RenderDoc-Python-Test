'''
author: v_sycisong
LastEditors: v_sycisong
'''

from global_config import cfg
cfg.setup_python_env()

import renderdoc_task
from stubs_generation.helpers import generator3
if __name__ == "__main__":
    generator3.main(['renderdoc', '-d', cfg.rdc_save_dir])
    generator3.main(['qrenderdoc', '-d', cfg.rdc_save_dir])