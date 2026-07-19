try:
    import evdev
    from evdev import ecodes, AbsInfo
except ImportError:
    evdev = None
    ecodes = None
    AbsInfo = None

import os
import subprocess
import time
import json
from typing import Dict
from core.input_interface import InputInterface

class LinuxInput(InputInterface):
    """
    Input via evdev uinput — keyboard AND mouse.
    Mouse uses EV_ABS (absolute movement) for Wayland/Hyprland compatibility
    without velocity-dependent pointer acceleration issues.
    Button events use EV_KEY (BTN_LEFT/BTN_RIGHT).
    """
    
    def __init__(self):
        if not evdev:
            raise ImportError("evdev is required. Install: pip install evdev")

        # Try to get screen resolution via hyprctl
        self.screen_width = 1920
        self.screen_height = 1080
        try:
            result = subprocess.run(
                ["hyprctl", "monitors", "-j"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                monitors = json.loads(result.stdout)
                if monitors:
                    self.screen_width = monitors[0].get("width", 1920)
                    self.screen_height = monitors[0].get("height", 1080)
        except Exception:
            pass

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
                ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE,
                ecodes.BTN_TOUCH,
            ],
            ecodes.EV_REL: [
                ecodes.REL_X,
                ecodes.REL_Y,
                ecodes.REL_WHEEL,
            ],
            ecodes.EV_ABS: [
                (ecodes.ABS_X, AbsInfo(value=0, min=0, max=self.screen_width, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_Y, AbsInfo(value=0, min=0, max=self.screen_height, fuzz=0, flat=0, resolution=0)),
            ]
        }

        try:
            self.ui = evdev.UInput(
                cap, 
                name='Forsaken-Auto-Input', 
                version=0x1,
                input_props=[ecodes.INPUT_PROP_POINTER],
            )
        except PermissionError:
            raise PermissionError("Could not create uinput device. Permission denied.")
        except TypeError:
            self.ui = evdev.UInput(cap, name='Forsaken-Auto-Input', version=0x1)

        self._key_map = self._build_key_map()

        # Internal cursor position tracking (absolute pixels on screen)
        self._cursor_x = self.screen_width // 2
        self._cursor_y = self.screen_height // 2

        print(f"   🖱️  Mouse: uinput EV_ABS (absolute mode) - {self.screen_width}x{self.screen_height}")

    @staticmethod
    def _ensure_ydotoold():
        """Start ydotoold daemon if not already running."""
        try:
            result = subprocess.run(
                ["pgrep", "-x", "ydotoold"],
                capture_output=True, timeout=2
            )
            if result.returncode != 0:
                subprocess.Popen(
                    ["ydotoold"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                time.sleep(0.3)
        except Exception:
            pass

    def absolute_move(self, x: int, y: int):
        """Move cursor to absolute position using EV_ABS."""
        target_x, target_y = int(x), int(y)
        self.ui.write(ecodes.EV_ABS, ecodes.ABS_X, target_x)
        self.ui.write(ecodes.EV_ABS, ecodes.ABS_Y, target_y)
        self.ui.syn()
        self._cursor_x = target_x
        self._cursor_y = target_y

    def set_screen_resolution(self, width: int, height: int):
        self.screen_width = width
        self.screen_height = height

    def sync_cursor_position(self):
        """Query actual cursor position from Hyprland and sync internal tracking."""
        try:
            result = subprocess.run(
                ["hyprctl", "cursorpos"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                parts = result.stdout.strip().replace(" ", "").split(",")
                if len(parts) == 2:
                    self._cursor_x = int(parts[0])
                    self._cursor_y = int(parts[1])
                    print(f"   🖱️  Cursor synced to ({self._cursor_x}, {self._cursor_y})")
                    return
        except Exception:
            pass
        self._cursor_x = self.screen_width // 2
        self._cursor_y = self.screen_height // 2
        print(f"   🖱️  Cursor position unknown, assuming center ({self._cursor_x}, {self._cursor_y})")

    def _build_key_map(self) -> Dict[str, int]:
        m = {
            'left': ecodes.KEY_LEFT, 'right': ecodes.KEY_RIGHT,
            'up': ecodes.KEY_UP, 'down': ecodes.KEY_DOWN,
            'enter': ecodes.KEY_ENTER, 'esc': ecodes.KEY_ESC,
            'space': ecodes.KEY_SPACE, 'j': ecodes.KEY_J,
            'f4': ecodes.KEY_F4, 'shift': ecodes.KEY_LEFTSHIFT,
            'ctrl': ecodes.KEY_LEFTCTRL, 'alt': ecodes.KEY_LEFTALT,
        }
        return m

    def _get_keycode(self, key_code: str):
        k = key_code.lower()
        if k in self._key_map:
            return self._key_map[k]
        try:
            return getattr(ecodes, f"KEY_{k.upper()}")
        except AttributeError:
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
        """Move mouse to absolute screen coordinates using EV_ABS."""
        self.absolute_move(x, y)


    def mouse_down(self, button: str = 'left'):
        btn_code = ecodes.BTN_LEFT if button == 'left' else ecodes.BTN_RIGHT
        self.ui.write(ecodes.EV_KEY, btn_code, 1)
        if button == 'left':
            self.ui.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, 1)
        self.ui.syn()

    def mouse_up(self, button: str = 'left'):
        btn_code = ecodes.BTN_LEFT if button == 'left' else ecodes.BTN_RIGHT
        self.ui.write(ecodes.EV_KEY, btn_code, 0)
        if button == 'left':
            self.ui.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, 0)
        self.ui.syn()

    def click(self, x: int, y: int, button: str = 'left'):
        self.move_mouse(x, y)
        self.mouse_down(button)
        time.sleep(0.01)
        self.mouse_up(button)

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.0):
        self.move_mouse(start_x, start_y)
        time.sleep(0.05)
        self.mouse_down()
        if duration > 0:
            steps = int(duration * 60)
            for i in range(steps):
                t = (i + 1) / steps
                self.move_mouse(
                    int(start_x + (end_x - start_x) * t),
                    int(start_y + (end_y - start_y) * t)
                )
                time.sleep(duration / steps)
        else:
            self.move_mouse(end_x, end_y)
        self.mouse_up()
