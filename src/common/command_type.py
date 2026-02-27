from enum import IntEnum

class CaptureFrameCommandType(IntEnum):
    Launch_RDC = 0
    Launch_APP = 1
    APP_CAPTURE = 2
    CLOSE_CONNNET = 3
    SET_DIR = 4
    SET_DEVICE_SERIAL= 5
