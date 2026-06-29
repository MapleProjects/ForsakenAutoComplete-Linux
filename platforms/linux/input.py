try:
    import evdev
    from evdev import ecodes
except ImportError:
    evdev = None
    ecodes = None

import time
import math
from typing import Dict
from core.input_interface import InputInterface

class LinuxInput(InputInterface):
    """
    Implementation of InputInterface using evdev for Linux (Kernel Level)
    """
    
    # Virtual Screen Resolution for Absolute Positioning
    # We use a high resolution to mapping effectively to any screen size
    ABS_MAX = 32768 

    def __init__(self):
        if not evdev:
            raise ImportError("evdev is required for LinuxInput. Run setup_linux.sh first.")

        # Define capabilities for the virtual device
        cap = {
            ecodes.EV_KEY: [
                ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT,
                ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL,
                ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT,
                ecodes.KEY_ENTER, ecodes.KEY_ESC, ecodes.KEY_BACKSPACE,
                ecodes.KEY_TAB, ecodes.KEY_SPACE,
                ecodes.KEY_UP, ecodes.KEY_DOWN, ecodes.KEY_LEFT, ecodes.KEY_RIGHT,
                ecodes.KEY_J, ecodes.KEY_W, ecodes.KEY_A, ecodes.KEY_S, ecodes.KEY_D,
                ecodes.KEY_F4, 
                # Mouse buttons
                ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE
            ],
            ecodes.EV_ABS: [
                (ecodes.ABS_X, evdev.AbsInfo(value=0, min=0, max=self.ABS_MAX, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_Y, evdev.AbsInfo(value=0, min=0, max=self.ABS_MAX, fuzz=0, flat=0, resolution=0)),
            ]
        }
        
        # Create virtual device
        # Note: 'uinput' device creation usually requires udev rules logic we set up in setup_linux.sh
        try:
            self.ui = evdev.UInput(cap, name='Forsaken-Auto-Input', version=0x1)
        except PermissionError:
            raise PermissionError("Could not create uinput device. Permission denied. Did you run setup_linux.sh and reload udev rules?")

        self._key_map = self._build_key_map()
        self.screen_width = 1920 # Default, should be updated by vision system or config
        self.screen_height = 1080

    def set_screen_resolution(self, width: int, height: int):
        self.screen_width = width
        self.screen_height = height

    def _build_key_map(self) -> Dict[str, int]:
        """Maps string representation to evdev keycodes"""
        m = {
            'left': ecodes.KEY_LEFT,
            'right': ecodes.KEY_RIGHT,
            'up': ecodes.KEY_UP,
            'down': ecodes.KEY_DOWN,
            'enter': ecodes.KEY_ENTER,
            'esc': ecodes.KEY_ESC,
            'space': ecodes.KEY_SPACE,
            'j': ecodes.KEY_J,
            'f4': ecodes.KEY_F4,
            'shift': ecodes.KEY_LEFTSHIFT,
            'ctrl': ecodes.KEY_LEFTCTRL,
            'alt': ecodes.KEY_LEFTALT,
        }
        return m

    def _get_keycode(self, key_code: str):
        k = key_code.lower()
        if k in self._key_map:
            return self._key_map[k]
        
        # Try finding by attribute name in ecodes
        try:
            return getattr(ecodes, f"KEY_{k.upper()}")
        except AttributeError:
            print(f"Warning: Key '{key_code}' not found in map.")
            return None

    def press(self, key_code: str):
        code = self._get_keycode(key_code)
        if code:
            self.ui.write(ecodes.EV_KEY, code, 1)
            self.ui.write(ecodes.EV_KEY, code, 0)
            self.ui.syn()

    def key_down(self, key_code: str):
        code = self._get_keycode(key_code)
        if code:
            self.ui.write(ecodes.EV_KEY, code, 1)
            self.ui.syn()

    def key_up(self, key_code: str):
        code = self._get_keycode(key_code)
        if code:
            self.ui.write(ecodes.EV_KEY, code, 0)
            self.ui.syn()

    def move_mouse(self, x: int, y: int):
        # Convert pixel coordinates to absolute device coordinates
        # x / width * ABS_MAX
        abs_x = int((x / self.screen_width) * self.ABS_MAX)
        abs_y = int((y / self.screen_height) * self.ABS_MAX)
        
        # Clamp
        abs_x = max(0, min(self.ABS_MAX, abs_x))
        abs_y = max(0, min(self.ABS_MAX, abs_y))

        self.ui.write(ecodes.EV_ABS, ecodes.ABS_X, abs_x)
        self.ui.write(ecodes.EV_ABS, ecodes.ABS_Y, abs_y)
        self.ui.syn()

    def mouse_down(self, button: str = 'left'):
        btn_code = ecodes.BTN_LEFT if button == 'left' else ecodes.BTN_RIGHT
        self.ui.write(ecodes.EV_KEY, btn_code, 1)
        self.ui.syn()

    def mouse_up(self, button: str = 'left'):
        btn_code = ecodes.BTN_LEFT if button == 'left' else ecodes.BTN_RIGHT
        self.ui.write(ecodes.EV_KEY, btn_code, 0)
        self.ui.syn()

    def click(self, x: int, y: int, button: str = 'left'):
        self.move_mouse(x, y)
        btn_code = ecodes.BTN_LEFT if button == 'left' else ecodes.BTN_RIGHT
        
        self.ui.write(ecodes.EV_KEY, btn_code, 1)
        self.ui.syn()
        time.sleep(0.01) # Small delay for registration
        self.ui.write(ecodes.EV_KEY, btn_code, 0)
        self.ui.syn()

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.0):
        self.move_mouse(start_x, start_y)
        time.sleep(0.05)
        
        self.ui.write(ecodes.EV_KEY, ecodes.BTN_LEFT, 1)
        self.ui.syn()
        
        if duration > 0:
            # Interpolate movement
            steps = int(duration * 60) # 60 Hz 
            for i in range(steps):
                t = (i + 1) / steps
                curr_x = int(start_x + (end_x - start_x) * t)
                curr_y = int(start_y + (end_y - start_y) * t)
                self.move_mouse(curr_x, curr_y)
                time.sleep(duration / steps)
        else:
            self.move_mouse(end_x, end_y)
            
        self.ui.write(ecodes.EV_KEY, ecodes.BTN_LEFT, 0)
        self.ui.syn()
