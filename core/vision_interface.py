from abc import ABC, abstractmethod
from typing import Tuple, Optional, Any
import numpy as np

class VisionInterface(ABC):
    """
    Abstract Base Class for Vision/Screen Capture
    """

    @abstractmethod
    def capture(self, region: Optional[Tuple[int, int, int, int]] = None) -> np.ndarray:
        """
        Capture the screen or a specific region.
        Returns a numpy array (BGR format for OpenCV).
        """
        pass

    @abstractmethod
    def get_resolution(self) -> Tuple[int, int]:
        """
        Return the current resolution (width, height) being utilized.
        """
        pass
