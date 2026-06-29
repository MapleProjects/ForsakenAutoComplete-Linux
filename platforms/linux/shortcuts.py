import evdev
from evdev import ecodes
import threading
import time
import os
import glob
from typing import Callable

class LinuxHotkeys:
    """
    Monitors input devices for Global Hotkeys (Killswitch) on Linux.
    Works on Wayland by reading raw /dev/input/events via 'uaccess' permissions.
    """
    
    def __init__(self):
        self.running = False
        self.callbacks = {}
        self.devices = []
        self.thread = None
    
    def register(self, key_name: str, callback: Callable):
        """
        Register a hotkey callback.
        key_name: 'F4', 'J', etc.
        """
        key_code = getattr(ecodes, f"KEY_{key_name.upper()}", None)
        if key_code:
            self.callbacks[key_code] = callback
            print(f"   ⌨️  Registered hotkey listener for: {key_name}")
        else:
            print(f"   ⚠️  Unknown key for hotkey: {key_name}")

    def start(self):
        """Start the monitoring thread"""
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
    
    def stop(self):
        self.running = False
        
    def _monitor_loop(self):
        """
        Scans for keyboards and listens to them.
        """
        # 1. Find Keyboards
        # Simple heuristic: Look for devices with EV_KEY capabilities that include KEY_ENTER
        print("   🔍 Scanning input devices...")
        available_devices = []
        try:
             # Try glob first to see what we can see
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
                        # Test read permission (should be fine if udev rule worked)
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

        # 2. Loop using select (or async, but thread with simple polling is fine for this)
        # We use a selector to listen to multiple fds
        import select
        
        fds = {dev.fd: dev for dev in keyboards}
        
        while self.running:
            r, w, x = select.select(fds, [], [], 0.5)
            for fd in r:
                dev = fds[fd]
                try:
                    for event in dev.read():
                        if event.type == ecodes.EV_KEY and event.value == 1: # Key Down
                            if event.code in self.callbacks:
                                print(f"   🛑 Hotkey Trigger: {event.code}")
                                self.callbacks[event.code]()
                except OSError:
                    # Device disconnected?
                    del fds[fd]
                    
            if not fds:
                break
