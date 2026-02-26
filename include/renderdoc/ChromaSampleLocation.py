# encoding: utf-8
# module renderdoc
# from c:\WorkSpace\Tools\rdcTest\lib\windows\renderdoc.pyd
# by generator 1.147
# no doc

# imports
import enum as __enum

from typing import List, Tuple, Callable, Any


class ChromaSampleLocation(__enum.IntEnum):
    """
    Determines where in the pixel downsampled chrome samples are positioned.
    
    .. data:: CositedEven
    
      The chroma samples are positioned exactly in the same place as the even luma co-ordinates.
    
    .. data:: Midpoint
    
      The chrome samples are positioned half way between each even luma sample and the next highest odd
      luma sample.
    """
    def __init__(self, *args, **kwargs): # real signature unknown
        pass

    CositedEven = 0
    """ The chroma samples are positioned exactly in the same place as the even luma co-ordinates. """

    Midpoint = 1
    """
    The chrome samples are positioned half way between each even luma sample and the next highest odd
      luma sample.
    """



