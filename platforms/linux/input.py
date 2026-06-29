try:
    import evdev
    from evdev import ecodes
except ImportError:
    evdev = None
    ecodes = None

import os
import subprocess
import time
import math
from typing import Dict
from core.input_interface import InputInterface

class LinuxInput(InputInterface):
    """
    Implementation of InputInterface using evdev (keyboard) + ydotool (mouse).
    evdev uinput for keyboard events, ydotool for mouse movement on Wayland.
    """
    
    # ydotool button codes
    _BTN_LEFT_DOWN = '0x40'
    _BTN_LEFT_UP   = '0x80'
    _BTN_LEFT_CLICK = '0xC0'
    _BTN_RIGHT_DOWN = '0x41'
    _BTN_RIGHT_UP   = '0x81'
    
    def __init__(self):
        if not evdev:
            raise ImportError("evdev is required for LinuxInput. Run setup_linux.sh first.")

        # Create uinput device for KEYBOARD events only
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
            ],
        }
        
        try:
            self.ui = evdev.UInput(cap, name='Forsaken-Auto-Input', version=0x1)
        except PermissionError:
            raise PermissionError("Could not create uinput device. Permission denied. Did you run setup_linux.sh and reload udev rules?")

        self._key_map = self._build_key_map()
        self.screen_width = 1920
        self.screen_height = 1080
        
        # Find ydotool socket
        self._ydotool_socket = self._find_ydotool_socket()

    def _find_ydotool_socket(self) -> str:
        """Find the ydotoold socket path."""
        # Check environment variable first
        env_socket = os.environ.get('YDOTOOL_SOCKET')
        if env_socket and os.path.exists(env_socket):
            return env_socket
        
        # Common locations
        uid = os.getuid()
        candidates = [
            f'/run/user/{uid}/.ydotool_socket',
            '/tmp/.ydotool_socket',
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        
        return f'/run/user/{uid}/.ydotool_socket'  # Default

    def _ydotool(self, *args):
        """Execute a ydotool command."""
        env = os.environ.copy()
        env['YDOTOOL_SOCKET'] = self._ydotool_socket
        try:
            subprocess.run(
                ['ydotool'] + [str(a) for a in args],
                env=env, capture_output=True, timeout=2
            )
        except FileNotFoundError:
            print("⚠️ ydotool not found. Install with: pacman -S ydotool")
        except subprocess.TimeoutExpired:
            pass  # Ignore timeouts on mouse moves

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

    # ===== MOUSE: via ydotool (Wayland-compatible) =====

    def move_mouse(self, x: int, y: int):
        self._ydotool('mousemove', '-a', '-x', str(int(x)), '-y', str(int(y)))

    def mouse_down(self, button: str = 'left'):
        btn = self._BTN_LEFT_DOWN if button == 'left' else self._BTN_RIGHT_DOWN
        self._ydotool('click', btn)

    def mouse_up(self, button: str = 'left'):
        btn = self._BTN_LEFT_UP if button == 'left' else self._BTN_RIGHT_UP
        self._ydotool('click', btn)

    def click(self, x: int, y: int, button: str = 'left'):
        self.move_mouse(x, y)
        time.sleep(0.02)
        btn = self._BTN_LEFT_CLICK if button == 'left' else '0xC1'
        self._ydotool('click', btn)

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.0):
        self.move_mouse(start_x, start_y)
        time.sleep(0.05)
        
        self.mouse_down()
        
        if duration > 0:
            steps = int(duration * 60)
            for i in range(steps):
                t = (i + 1) / steps
                curr_x = int(start_x + (end_x - start_x) * t)
                curr_y = int(start_y + (end_y - start_y) * t)
                self.move_mouse(curr_x, curr_y)
                time.sleep(duration / steps)
        else:
            self.move_mouse(end_x, end_y)
            
        self.mouse_up()
