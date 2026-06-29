import os
import subprocess
import numpy as np
import cv2
from typing import Tuple, Optional
from core.vision_interface import VisionInterface


class LinuxVision(VisionInterface):
    """
    Implementation of VisionInterface using grim (Wayland-native screenshot tool).
    Instant capture, no X11/PipeWire/MSS dependencies.
    Works on Hyprland, Sway, and any wlroots-based compositor.
    """

    def __init__(self, monitor_idx: int = 1):
        self.monitor_idx = monitor_idx
        self.width = 1920
        self.height = 1080
        self._tmp_path = "/tmp/forsaken_capture.png"

        # Detect resolution from grim
        try:
            result = subprocess.run(
                ["grim", "-g", "0,0 1x1", "-"],
                capture_output=True, timeout=5
            )
            # Get actual resolution from display info
            # Fallback: capture full screen once and read dimensions
            self._detect_resolution()
        except Exception as e:
            print(f"⚠️ grim init warning: {e}")

        print(f"🖥️  Screen resolution: {self.width}x{self.height}")

    def _detect_resolution(self):
        """Detect screen resolution by capturing a tiny region and checking display info."""
        try:
            # Use wlr-randr or swaymsg to get resolution
            result = subprocess.run(
                ["swaymsg", "-t", "get_outputs", "-r"],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0:
                import json
                outputs = json.loads(result.stdout)
                if outputs:
                    rect = outputs[0].get("rect", {})
                    self.width = rect.get("width", 1920)
                    self.height = rect.get("height", 1080)
                    return
        except Exception:
            pass

        # Fallback: Hyprland
        try:
            result = subprocess.run(
                ["hyprctl", "monitors", "-j"],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0:
                import json
                monitors = json.loads(result.stdout)
                if monitors:
                    self.width = monitors[0].get("width", 1920)
                    self.height = monitors[0].get("height", 1080)
                    return
        except Exception:
            pass

        # Final fallback: capture full screen and read dimensions
        try:
            subprocess.run(
                ["grim", self._tmp_path],
                capture_output=True, timeout=5
            )
            img = cv2.imread(self._tmp_path)
            if img is not None:
                self.height, self.width = img.shape[:2]
            os.remove(self._tmp_path)
        except Exception:
            pass

    def capture(self, region: Optional[Tuple[int, int, int, int]] = None) -> np.ndarray:
        """
        Capture screen or a specific region using grim.
        region = (left, top, width, height)
        """
        try:
            if region:
                left, top, w, h = region
                # grim geometry format: "x,y wxh"
                geometry = f"{int(left)},{int(top)} {int(w)}x{int(h)}"
                cmd = ["grim", "-g", geometry, self._tmp_path]
            else:
                cmd = ["grim", self._tmp_path]

            result = subprocess.run(cmd, capture_output=True, timeout=5)

            if result.returncode != 0:
                print(f"❌ grim error: {result.stderr.decode().strip()}")
                return np.zeros((self.height, self.width, 3), dtype=np.uint8)

            img = cv2.imread(self._tmp_path)
            if img is None:
                print("❌ Failed to read captured image")
                return np.zeros((self.height, self.width, 3), dtype=np.uint8)

            # Update resolution from full screen capture
            if region is None:
                self.height, self.width = img.shape[:2]

            return img

        except subprocess.TimeoutExpired:
            print("❌ grim timeout (5s)")
            return np.zeros((self.height, self.width, 3), dtype=np.uint8)
        except Exception as e:
            print(f"❌ grim failed: {e}")
            return np.zeros((self.height, self.width, 3), dtype=np.uint8)

    def get_resolution(self) -> Tuple[int, int]:
        return (self.width, self.height)
