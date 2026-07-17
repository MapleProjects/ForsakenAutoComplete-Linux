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
    Mouse uses EV_REL (relative movement) for Wayland/Hyprland compatibility.
    Button events use EV_KEY (BTN_LEFT/BTN_RIGHT).
    """
    
    def __init__(self):
        if not evdev:
            raise ImportError("evdev is required. Install: pip install evdev")

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
            ],
            ecodes.EV_REL: [
                ecodes.REL_X,
                ecodes.REL_Y,
                ecodes.REL_WHEEL,
            ],
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
            # Older evdev may not support input_props
            self.ui = evdev.UInput(cap, name='Forsaken-Auto-Input', version=0x1)

        self._key_map = self._build_key_map()
        self.screen_width = 1920
        self.screen_height = 1080
        
        # Internal cursor position tracking (absolute pixels on screen)
        # Start at center of screen
        self._cursor_x = self.screen_width // 2
        self._cursor_y = self.screen_height // 2
        
        print(f"   🖱️  Mouse: uinput EV_REL + ydotool absolute (pointer mode)")
        
        # Detect EV_REL to screen pixel scale factor
        self._detect_evrel_scale()

    def _detect_evrel_scale(self):
        """Detect EV_REL to screen pixel scale factor by measuring actual cursor movement."""
        self._evrel_scale_x = 1.0
        self._evrel_scale_y = 1.0
        
        def get_cursor_pos():
            try:
                result = subprocess.run(["hyprctl", "cursorpos"], capture_output=True, text=True, timeout=2)
                if result.returncode == 0:
                    parts = result.stdout.strip().replace(" ", "").split(",")
                    if len(parts) == 2:
                        return int(parts[0]), int(parts[1])
            except:
                pass
            return None, None
        
        # Calibrate X
        start = get_cursor_pos()
        if start:
            self.ui.write(ecodes.EV_REL, ecodes.REL_X, 300)
            self.ui.syn()
            time.sleep(0.1)
            end = get_cursor_pos()
            if end:
                actual = end[0] - start[0]
                if actual != 0:
                    self._evrel_scale_x = 300.0 / actual
                # Move back
                self.ui.write(ecodes.EV_REL, ecodes.REL_X, -300)
                self.ui.syn()
                time.sleep(0.1)
        
        # Calibrate Y
        start = get_cursor_pos()
        if start:
            self.ui.write(ecodes.EV_REL, ecodes.REL_Y, 300)
            self.ui.syn()
            time.sleep(0.1)
            end = get_cursor_pos()
            if end:
                actual = end[1] - start[1]
                if actual != 0:
                    self._evrel_scale_y = 300.0 / actual
                # Move back
                self.ui.write(ecodes.EV_REL, ecodes.REL_Y, -300)
                self.ui.syn()
                time.sleep(0.1)
        
        # Clamp
        self._evrel_scale_x = max(0.1, min(5.0, self._evrel_scale_x))
        self._evrel_scale_y = max(0.1, min(5.0, self._evrel_scale_y))
        
        print(f"   📏 EV_REL scale: X={self._evrel_scale_x:.4f}, Y={self._evrel_scale_y:.4f}")

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
        """Move cursor to absolute position.

        Uses internal tracking only — no hyprctl sync during drawing.
        hyprctl cursorpos returns the PHYSICAL mouse cursor position,
        not the virtual uinput device cursor. Mixing them causes drift.
        """
        target_x, target_y = int(x), int(y)
        self.move_mouse(target_x, target_y)

    def set_screen_resolution(self, width: int, height: int):
        self.screen_width = width
        self.screen_height = height
        # NOTE: Do NOT call sync_cursor_position here.
        # hyprctl returns the physical mouse position, not the uinput virtual cursor.
        # The virtual cursor starts at screen center (set in __init__).

    def sync_cursor_position(self):
        """Query actual cursor position from Hyprland and sync internal tracking."""
        try:
            result = subprocess.run(
                ["hyprctl", "cursorpos"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                # Output format: "1234, 567" or "1234,567"
                parts = result.stdout.strip().replace(" ", "").split(",")
                if len(parts) == 2:
                    self._cursor_x = int(parts[0])
                    self._cursor_y = int(parts[1])
                    print(f"   🖱️  Cursor synced to ({self._cursor_x}, {self._cursor_y})")
                    return
        except Exception:
            pass
        # Fallback: assume center of screen
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
        """Move mouse to absolute screen coordinates using relative deltas."""
        # Calculate delta from current tracked position
        delta_x = int(x) - int(self._cursor_x)
        delta_y = int(y) - int(self._cursor_y)
        
        # Apply EV_REL scale factor (compositor may scale input events)
        delta_x = int(delta_x / self._evrel_scale_x)
        delta_y = int(delta_y / self._evrel_scale_y)
        
        # Clamp deltas to int16 range (evdev uses int16 for REL)
        delta_x = max(-32768, min(32767, delta_x))
        delta_y = max(-32768, min(32767, delta_y))
        
        # Send relative movement
        if delta_x != 0:
            self.ui.write(ecodes.EV_REL, ecodes.REL_X, delta_x)
        if delta_y != 0:
            self.ui.write(ecodes.EV_REL, ecodes.REL_Y, delta_y)
        self.ui.syn()
        
        # Update internal position tracking
        self._cursor_x = int(x)
        self._cursor_y = int(y)

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
        time.sleep(0.01)
        self.ui.write(ecodes.EV_KEY, btn_code, 0)
        self.ui.syn()

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
