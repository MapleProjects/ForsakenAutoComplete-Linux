#!/bin/bash
# Forsaken AutoComplete - Linux Bootstrapper for Arch/CachyOS/EndeavourOS
# Installs dependencies and configures udev rules for passwordless input injection.

set -e

echo "🐧 Forsaken AutoComplete: Linux Setup"
echo "======================================"

# 1. Check for Arch-based distro
if [ ! -f /etc/arch-release ]; then
    echo "⚠️  Warning: This script is optimized for Arch Linux / EndeavourOS / CachyOS."
    echo "    On other distros, you might need to install 'python-evdev' manually."
    read -p "    Press Enter to continue anyway, or Ctrl+C to abort..."
fi

# 2. Install System Dependencies
echo -e "\n📦 Installing system dependencies (pacman)..."
sudo pacman -S --needed --noconfirm \
    python-evdev \
    tk \
    python-pynput \
    python-opencv \
    python-numpy \
    python-pillow \
    grim \
    ydotool \
    jq

# 3. Install Python Dependencies
echo -e "\n🐍 Installing Python dependencies..."
pip install --break-system-packages platformdirs evdev mss

# 4. Configure udev rules for uinput (The "Magic" part)
echo -e "\n🔑 Configuring permissions for input injection..."
UDEV_RULE_PATH="/etc/udev/rules.d/99-forsaken-input.rules"

RULE_CONTENT='KERNEL=="uinput", SUBSYSTEM=="misc", OPTIONS+="static_node=uinput", TAG+="uaccess"'

if [ -f "$UDEV_RULE_PATH" ]; then
    echo "   ✅ udev rule already exists."
else
    echo "   📝 Writing udev rule to $UDEV_RULE_PATH..."
    echo "$RULE_CONTENT" | sudo tee "$UDEV_RULE_PATH" > /dev/null
    echo "   🔄 Reloading udev rules..."
    sudo udevadm control --reload-rules
    sudo udevadm trigger
    echo "   ✅ Rules applied. You may need to logout and login for them to take full effect."
fi

# 5. Load uinput module just in case
if ! lsmod | grep -q uinput; then
    echo "   🔌 Loading kernel module 'uinput'..."
    sudo modprobe uinput
fi

echo -e "\n✨ Setup Complete! You can now run the solver."
echo "   Run: python flow_solver.py"
echo "   NOTE: If input injection fails, try restarting your session."
