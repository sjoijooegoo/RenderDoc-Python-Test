'''
author: v_sycisong
LastEditors: v_sycisong
'''
import renderdoc as rd
from typing import Tuple

def loadCapture(filename) -> Tuple[rd.ResultDetails, rd.ReplayController]:
	cap = rd.OpenCaptureFile()

	result = cap.OpenFile(filename, '', None)

	if result != rd.ResultCode.Succeeded:
		raise RuntimeError("Couldn't open file: " + str(result))

	if not cap.LocalReplaySupport():
		raise RuntimeError("Capture cannot be replayed")

	result,controller = cap.OpenCapture(rd.ReplayOptions(), None)
 
	if result != rd.ResultCode.Succeeded:
		raise RuntimeError("Couldn't initialise replay: " + str(result))

	return (cap, controller)

def list_events(controller: rd.ReplayController):
    return controller.GetRootActions()