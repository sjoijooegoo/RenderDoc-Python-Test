# encoding: utf-8
# module renderdoc
# from c:\WorkSpace\Tools\rdcTest\lib\windows\renderdoc.pyd
# by generator 1.147
# no doc

# imports
import enum as __enum

from typing import List, Tuple, Callable, Any


class DescriptorCategory(__enum.IntEnum):
    """
    The category of a descriptor, corresponding to the interfaces in :class:`ShaderReflection`.
    
    .. data:: Unknown
    
      An unknown or uninitialised type of descriptor.
    
    .. data:: ConstantBlock
    
      A constant block.
    
    .. data:: Sampler
    
      A sampler object.
    
    .. data:: ReadOnlyResource
    
      A read-only resource.
    
    .. data:: ReadWriteResource
    
      A read-write resource.
    """
    def __init__(self, *args, **kwargs): # real signature unknown
        pass

    ConstantBlock = 1
    """ A constant block. """

    ReadOnlyResource = 3
    """ A read-only resource. """

    ReadWriteResource = 4
    """ A read-write resource. """

    Sampler = 2
    """ A sampler object. """

    Unknown = 0
    """ An unknown or uninitialised type of descriptor. """



