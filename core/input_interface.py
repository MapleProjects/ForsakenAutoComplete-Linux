from abc import ABC, abstractmethod
from typing import Tuple, Optional
import numpy as np

class InputInterface(ABC):
    """
    Abstract Base Class for Input Devices (Keyboard/Mouse)
    """

    @abstractmethod
    def press(self, key_code: str):
        """Press and release a key"""
        pass

    @abstractmethod
    def key_down(self, key_code: str):
        """Hold a key down"""
        pass

    @abstractmethod
    def key_up(self, key_code: str):
        """Release a key"""
        pass

    @abstractmethod
    def move_mouse(self, x: int, y: int):
        """Move mouse to absolute coordinates"""
        pass

    @abstractmethod
    def mouse_down(self, button: str = 'left'):
        """Press mouse button down"""
        pass

    @abstractmethod
    def mouse_up(self, button: str = 'left'):
        """Release mouse button"""
        pass
        
    @abstractmethod
    def click(self, x: int, y: int, button: str = 'left'):
        """Click at current or specific position"""
        pass

    @abstractmethod
    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.0):
        """Drag from start to end"""
        pass
