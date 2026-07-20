try:
    import evdev
    from evdev import ecodes
except ImportError:
    evdev = None
    ecodes = None

import os
import subprocess
import time
import json
from typing import Dict
from core.input_interface import InputInterface

class LinuxInput(InputInterface):
    """
    Input via evdev uinput — keyboard AND mouse.
    Uses Hyprland's native Lua dispatcher for absolute warping,
    and EV_REL relative virtual mouse movements for precise drawing.
    Pure relative mouse emulation (no EV_ABS) prevents the compositor
    from ignoring relative events during active clicks/drags.
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
                ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE, ecodes.BTN_TOUCH,
            ],
            ecodes.EV_REL: [
                ecodes.REL_X,
                ecodes.REL_Y,
                ecodes.REL_WHEEL,
            ]
        }

        try:
            self.ui = evdev.UInput(
                cap, 
                name='Forsaken-Auto-Input', 
                version=0x3,
                input_props=[ecodes.INPUT_PROP_POINTER],
            )
        except PermissionError:
            raise PermissionError("Could not create uinput device. Permission denied.")
        except TypeError:
            self.ui = evdev.UInput(cap, name='Forsaken-Auto-Input', version=0x3)

        # Allow compositor to register the virtual device
        time.sleep(1.0)

        self._key_map = self._build_key_map()

        # Internal cursor position tracking (absolute pixels on screen)
        self._cursor_x = self.screen_width // 2
        self._cursor_y = self.screen_height // 2

        # EV_REL relative drawing scale (1:1 direct mapping for exact pixel deltas)
        self._ev_scale_x = 1.0
        self._ev_scale_y = 1.0

        print(f"   🖱️  Mouse: Hybrid Native-Warp/EV_REL mode - {self.screen_width}x{self.screen_height}")

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

    def _get_cursor_pos_hyprctl_internal(self):
        try:
            result = subprocess.run(
                ["hyprctl", "cursorpos"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                parts = result.stdout.strip().replace(" ", "").split(",")
                if len(parts) == 2:
                    return int(parts[0]), int(parts[1])
        except Exception:
            pass
        return None, None

    def absolute_move(self, x: int, y: int):
        """Move cursor to absolute position using uinput EV_REL deltas and Hyprland dispatcher."""
        target_x, target_y = int(x), int(y)
        delta_x = target_x - int(self._cursor_x)
        delta_y = target_y - int(self._cursor_y)

        dist = max(abs(delta_x), abs(delta_y))
        if dist > 0:
            steps = max(1, int(dist / 30))
            curr_x = self._cursor_x
            curr_y = self._cursor_y
            for s in range(1, steps + 1):
                t = s / steps
                cx = int(curr_x + delta_x * t)
                cy = int(curr_y + delta_y * t)
                dx = cx - self._cursor_x
                dy = cy - self._cursor_y
                if dx != 0:
                    self.ui.write(ecodes.EV_REL, ecodes.REL_X, dx)
                if dy != 0:
                    self.ui.write(ecodes.EV_REL, ecodes.REL_Y, dy)
                self.ui.syn()
                self._cursor_x = cx
                self._cursor_y = cy
                time.sleep(0.003)

        try:
            subprocess.run(
                ["hyprctl", "dispatch", f"hl.dsp.cursor.move({{x={target_x}, y={target_y}}})"],
                capture_output=True, timeout=2
            )
        except Exception:
            pass
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
        """Move mouse to target coordinates using direct 1:1 EV_REL deltas and sync compositor."""
        delta_x = int(x) - int(self._cursor_x)
        delta_y = int(y) - int(self._cursor_y)

        ev_delta_x = max(-32768, min(32767, delta_x))
        ev_delta_y = max(-32768, min(32767, delta_y))

        if ev_delta_x != 0:
            self.ui.write(ecodes.EV_REL, ecodes.REL_X, ev_delta_x)
        if ev_delta_y != 0:
            self.ui.write(ecodes.EV_REL, ecodes.REL_Y, ev_delta_y)
        self.ui.syn()

        try:
            subprocess.run(
                ["hyprctl", "dispatch", f"hl.dsp.cursor.move({{x={int(x)}, y={int(y)}}})"],
                capture_output=True, timeout=2
            )
        except Exception:
            pass

        self._cursor_x = int(x)
        self._cursor_y = int(y)

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
