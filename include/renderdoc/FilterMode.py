# encoding: utf-8
# module renderdoc
# from c:\WorkSpace\Tools\rdcTest\lib\windows\renderdoc.pyd
# by generator 1.147
# no doc

# imports
import enum as __enum

from typing import List, Tuple, Callable, Any


class FilterMode(__enum.IntEnum):
    """
    The texture filtering mode for a given direction (minification, magnification, or
    between mips).
    
    .. data:: NoFilter
    
      No filtering - this direction is disabled or there is no sampler.
    
    .. data:: Point
    
      Point or nearest filtering - the closest pixel or mip level to the sample location is used.
    
    .. data:: Linear
    
      Linear filtering - a linear interpolation happens between the pixels or mips on either side of the
      sample location in each direction.
    
    .. data:: Cubic
    
      Similar to linear filtering but with a cubic curve used for interpolation instead of linear.
    
    .. data:: Anisotropic
    
      This sampler is using anisotropic filtering.
    """
    def __init__(self, *args, **kwargs): # real signature unknown
        pass

    Anisotropic = 4
    """ This sampler is using anisotropic filtering. """

    Cubic = 3
    """ Similar to linear filtering but with a cubic curve used for interpolation instead of linear. """

    Linear = 2
    """
    Linear filtering - a linear interpolation happens between the pixels or mips on either side of the
      sample location in each direction.
    """

    NoFilter = 0
    """ No filtering - this direction is disabled or there is no sampler. """

    Point = 1
    """ Point or nearest filtering - the closest pixel or mip level to the sample location is used. """



