import evdev
from evdev import ecodes
import threading
import select
import glob
from typing import Callable, Dict, Set

class LinuxHotkeys:
    """
    Full keyboard manager via evdev for Wayland.
    Handles hotkeys (F4, Alt+J), solver trigger (J), and human interrupt detection (WASD/arrows).
    No pynput needed.
    """

    MODIFIER_CODES = {
        ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT,
        ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL,
        ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT,
    }

    # Movement keys that indicate human input
    MOVEMENT_CODES = {
        ecodes.KEY_W, ecodes.KEY_A, ecodes.KEY_S, ecodes.KEY_D,
        ecodes.KEY_UP, ecodes.KEY_DOWN, ecodes.KEY_LEFT, ecodes.KEY_RIGHT,
        ecodes.KEY_SPACE, ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT,
    }

    def __init__(self):
        self.running = False
        self.single_callbacks: Dict[int, Callable] = {}
        self.combo_callbacks: Dict[tuple, Callable] = {}
        self.movement_callback: Callable = None
        self.thread = None
        self.pressed_modifiers: Set[int] = set()
        self.devices = []

    def register(self, key_name: str, callback: Callable):
        """Register a single-key hotkey (F4, J, etc.)"""
        key_code = getattr(ecodes, f"KEY_{key_name.upper()}", None)
        if key_code:
            self.single_callbacks[key_code] = callback
            print(f"   ⌨️  Registered hotkey listener for: {key_name}")

    def register_combo(self, combo: str, callback: Callable):
        """
        Register a modifier+key combo callback.
        combo format: 'alt+j', 'ctrl+shift+s', etc.
        """
        parts = [p.strip().lower() for p in combo.split('+')]
        if len(parts) < 2:
            print(f"   ⚠️  Invalid combo format: {combo}")
            return

        key_name = parts[-1]
        key_code = getattr(ecodes, f"KEY_{key_name.upper()}", None)
        if not key_code:
            print(f"   ⚠️  Unknown key in combo: {key_name}")
            return

        # Each mod group is a frozenset of equivalent keys (e.g. LEFTALT or RIGHTALT)
        # User must hold at least one from each group
        mod_groups = []
        for m in parts[:-1]:
            if m == 'alt':
                mod_groups.append(frozenset({ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT}))
            elif m == 'ctrl':
                mod_groups.append(frozenset({ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL}))
            elif m == 'shift':
                mod_groups.append(frozenset({ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT}))
            else:
                print(f"   ⚠️  Unknown modifier: {m}")
                return

        self.combo_callbacks[(tuple(mod_groups), key_code)] = callback
        print(f"   ⌨️  Registered combo listener for: {combo}")

    def register_movement_interrupt(self, callback: Callable):
        """Register callback for when user presses movement keys (WASD, arrows, space, shift)"""
        self.movement_callback = callback

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False

    def _find_keyboards(self):
        """Find accessible keyboard devices"""
        keyboards = []
        paths = glob.glob('/dev/input/event*')

        for path in paths:
            try:
                d = evdev.InputDevice(path)
                caps = d.capabilities()
                if ecodes.EV_KEY in caps and ecodes.KEY_ENTER in caps[ecodes.EV_KEY]:
                    try:
                        d.grab()
                        d.ungrab()
                        keyboards.append(d)
                        print(f"   ✅ Keyboard: {d.name} ({d.path})")
                    except OSError:
                        pass
            except Exception:
                pass

        return keyboards

    def _monitor_loop(self):
        print("   🔍 Scanning keyboards...")
        keyboards = self._find_keyboards()

        if not keyboards:
            print("   ⚠️  No accessible keyboards found.")
            return

        fds = {dev.fd: dev for dev in keyboards}

        while self.running:
            r, _, _ = select.select(fds, [], [], 0.5)
            for fd in r:
                dev = fds[fd]
                try:
                    for event in dev.read():
                        if event.type != ecodes.EV_KEY:
                            continue

                        # Track modifiers
                        if event.code in self.MODIFIER_CODES:
                            if event.value in (1, 2):
                                self.pressed_modifiers.add(event.code)
                            elif event.value == 0:
                                self.pressed_modifiers.discard(event.code)
                            continue

                        # Only key-down events
                        if event.value != 1:
                            continue

                        # Check movement keys (human interrupt)
                        if event.code in self.MOVEMENT_CODES and self.movement_callback:
                            if not self.pressed_modifiers:
                                self.movement_callback()
                                continue

                        # Check single-key callbacks (F4, J)
                        if event.code in self.single_callbacks:
                            if not self.pressed_modifiers:
                                self.single_callbacks[event.code]()

                        # Check combo callbacks (Alt+J, etc.)
                        active_mods = frozenset(self.pressed_modifiers)
                        for (mod_groups, key_code), callback in self.combo_callbacks.items():
                            if event.code == key_code:
                                # Check at least one key from each mod group is held
                                if all(group & active_mods for group in mod_groups):
                                    callback()
                                    break

                except OSError:
                    del fds[fd]

            if not fds:
                break
