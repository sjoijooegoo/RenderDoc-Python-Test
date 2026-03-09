# encoding: utf-8
# module renderdoc
# from c:\WorkSpace\Tools\rdcTest\lib\windows\renderdoc.pyd
# by generator 1.147
# no doc

# imports
import enum as __enum

from typing import List, Tuple, Callable, Any


class AndroidFlags(__enum.IntFlag):
    """
    INTERNAL: A set of flags giving details of the current status of Android tracability.
    
    .. data:: NoFlags
    
      There are no problems with the Android application setup.
    
    .. data:: Debuggable
    
      The application is debuggable.
    
    .. data:: RootAccess
    
       The device being targeted has root access.
    """
    def __init__(self, *args, **kwargs): # real signature unknown
        pass

    Debuggable = 1
    """ The application is debuggable. """

    NoFlags = 0
    """ There are no problems with the Android application setup. """

    RootAccess = 2
    """ The device being targeted has root access. """



