# encoding: utf-8
# module renderdoc
# from c:\WorkSpace\Tools\rdcTest\lib\windows\renderdoc.pyd
# by generator 1.147
# no doc

# imports
import enum as __enum

from typing import List, Tuple, Callable, Any


class YcbcrRange(__enum.IntEnum):
    """
    Specifies the range of encoded values and their interpretation.
    
    .. data:: ITUFull
    
      The full range of input values are valid and interpreted according to ITU "full range" rules.
    
    .. data:: ITUNarrow
    
      A head and foot are reserved in the encoded values, and the remaining values are expanded
      according to "narrow range" rules.
    """
    def __init__(self, *args, **kwargs): # real signature unknown
        pass

    ITUFull = 0
    """ The full range of input values are valid and interpreted according to ITU "full range" rules. """

    ITUNarrow = 1
    """
    A head and foot are reserved in the encoded values, and the remaining values are expanded
      according to "narrow range" rules.
    """



