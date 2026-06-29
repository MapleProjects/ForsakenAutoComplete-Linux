import evdev
from evdev import ecodes
import threading
import select
import glob
from typing import Callable, Dict, Tuple, Set

class LinuxHotkeys:
    """
    Monitors input devices for Global Hotkeys on Linux.
    Works on Wayland by reading raw /dev/input/events via 'uaccess' permissions.
    Supports single keys AND modifier combos (e.g. alt+j).
    """

    # Modifier key codes
    MODIFIER_CODES = {
        ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT,
        ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL,
        ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT,
    }

    def __init__(self):
        self.running = False
        self.single_callbacks: Dict[int, Callable] = {}
        self.combo_callbacks: Dict[Tuple[frozenset, int], Callable] = {}
        self.devices = []
        self.thread = None
        self.pressed_modifiers: Set[int] = set()

    def register(self, key_name: str, callback: Callable):
        """
        Register a single-key hotkey callback.
        key_name: 'F4', 'J', etc.
        """
        key_code = getattr(ecodes, f"KEY_{key_name.upper()}", None)
        if key_code:
            self.single_callbacks[key_code] = callback
            print(f"   ⌨️  Registered hotkey listener for: {key_name}")
        else:
            print(f"   ⚠️  Unknown key for hotkey: {key_name}")

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
        mod_names = parts[:-1]

        key_code = getattr(ecodes, f"KEY_{key_name.upper()}", None)
        if not key_code:
            print(f"   ⚠️  Unknown key in combo: {key_name}")
            return

        mod_codes = set()
        for m in mod_names:
            if m == 'alt':
                mod_codes.update({ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT})
            elif m == 'ctrl':
                mod_codes.update({ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL})
            elif m == 'shift':
                mod_codes.update({ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT})
            else:
                print(f"   ⚠️  Unknown modifier: {m}")
                return

        # Store as frozenset of active mods -> key_code
        self.combo_callbacks[(frozenset(mod_codes), key_code)] = callback
        print(f"   ⌨️  Registered combo listener for: {combo}")

    def start(self):
        """Start the monitoring thread"""
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False

    def _monitor_loop(self):
        """Scans for keyboards and listens to them."""
        print("   🔍 Scanning input devices...")
        available_devices = []
        try:
            paths = glob.glob('/dev/input/event*')
            print(f"      Visible files: {len(paths)}")

            for path in paths:
                try:
                    d = evdev.InputDevice(path)
                    available_devices.append(d)
                except Exception as ex:
                    print(f"      ❌ Failed to open {path}: {ex}")

        except Exception as e:
            print(f"   ❌ Error listing devices: {e}")

        keyboards = []

        for dev in available_devices:
            print(f"      - Device: {dev.name} ({dev.path})")
            caps = dev.capabilities()
            if ecodes.EV_KEY in caps:
                if ecodes.KEY_ENTER in caps[ecodes.EV_KEY]:
                    try:
                        dev.grab()
                        dev.ungrab()
                        keyboards.append(dev)
                        print(f"        ✅ Identified as Keyboard (Active)")
                    except OSError as e:
                        print(f"        ⛔ No permission: {e}")
                else:
                    print("        (Skipped: No ENTER key)")
            else:
                print("        (Skipped: No EV_KEY)")

        if not keyboards:
            print("   ⚠️  No accessible keyboards found. Killswitch might not work.")
            return

        fds = {dev.fd: dev for dev in keyboards}

        while self.running:
            r, w, x = select.select(fds, [], [], 0.5)
            for fd in r:
                dev = fds[fd]
                try:
                    for event in dev.read():
                        if event.type != ecodes.EV_KEY:
                            continue

                        # Track modifier state
                        if event.code in self.MODIFIER_CODES:
                            if event.value in (1, 2):  # Down or repeat
                                self.pressed_modifiers.add(event.code)
                            elif event.value == 0:  # Up
                                self.pressed_modifiers.discard(event.code)
                            continue

                        # Only trigger on key down (value == 1)
                        if event.value != 1:
                            continue

                        # Check single-key callbacks
                        if event.code in self.single_callbacks:
                            # Don't fire single key if modifiers are held
                            if not self.pressed_modifiers:
                                print(f"   🛑 Hotkey Trigger: {ecodes.KEY.get(event.code, event.code)}")
                                self.single_callbacks[event.code]()

                        # Check combo callbacks
                        active_mods = frozenset(self.pressed_modifiers)
                        for (mod_set, key_code), callback in self.combo_callbacks.items():
                            if event.code == key_code and active_mods == mod_set:
                                mod_names = [ecodes.KEY.get(m, str(m)) for m in active_mods]
                                print(f"   🛑 Combo Trigger: {'+'.join(mod_names)}+{ecodes.KEY.get(key_code, key_code)}")
                                callback()
                                break

                except OSError:
                    del fds[fd]

            if not fds:
                break
