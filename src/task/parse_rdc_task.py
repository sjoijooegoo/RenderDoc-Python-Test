'''
author: v_sycisong
LastEditors: v_sycisong
'''
import os
from typing import Tuple
from . import task_manager
import renderdoc as rd

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

def printVar(v, indent = ''):
	print(indent + v.name + ":")

	if len(v.members) == 0:
		valstr = ""
		for r in range(0, v.rows):
			valstr += indent + '  '

			for c in range(0, v.columns):
				valstr += '%.3f ' % v.value.f32v[r*v.columns + c]

			if r < v.rows-1:
				valstr += "\n"

		print(valstr)

	for v in v.members:
		printVar(v, indent + '    ')

def sampleCode(controller: rd.ReplayController):
	print("Available disassembly formats:")

	targets = controller.GetDisassemblyTargets(True)

	for disasm in targets:
		print("  - " + disasm)

	target = targets[0]

	state = controller.GetPipelineState()
	# For some APIs, it might be relevant to set the PSO id or entry point name
	pipe = state.GetGraphicsPipelineObject()
	entry = state.GetShaderEntryPoint(rd.ShaderStage.Pixel)

	# Get the pixel shader's reflection object
	ps = state.GetShaderReflection(rd.ShaderStage.Pixel)
	files = ps.debugInfo.files
	for file in files:
		print(file.contents)
  
	vs = state.GetShaderReflection(rd.ShaderStage.Vertex)
 
	files = vs.debugInfo.files
	for file in files:
		print(file.contents)
 
	cb = state.GetConstantBlock(rd.ShaderStage.Pixel, 0, 0)

	print("Pixel shader:")
	disasm_text = controller.DisassembleShader(pipe, ps, target)
	shader_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "shader", "shader.frag"))
	with open(shader_path, "w", encoding="utf-8") as shader_file:
		shader_file.write(disasm_text)

	cbufferVars = controller.GetCBufferVariableContents(pipe, ps.resourceId, rd.ShaderStage.Pixel, entry, 0, cb.descriptor.resource, 0, 0)

	for v in cbufferVars:
		printVar(v)
     
@task_manager.manager.register
class ParseRdcTask:
    TASK_ID = "parse_rdc"
    
    def execute(self, args, params):
        try:
            if 'path' in params:
                file_path = params.get('path')
                cap, controller = loadCapture(file_path)
                controller.SetFrameEvent(12,True)
                sampleCode(controller)
        except Exception as e:
            print(f"parse_rdc_task: {e}")   