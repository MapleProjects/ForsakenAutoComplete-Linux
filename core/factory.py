from typing import Tuple
from core.input_interface import InputInterface
from core.vision_interface import VisionInterface

def get_platform_adapters() -> Tuple[InputInterface, VisionInterface]:
    """
    Returns the appropriate Input and Vision adapters for Linux.
    """
    from platforms.linux.input import LinuxInput
    from platforms.linux.vision import LinuxVision

    vision = LinuxVision()
    return LinuxInput(), vision

def get_hotkey_manager():
    from platforms.linux.shortcuts import LinuxHotkeys
    return LinuxHotkeys()
