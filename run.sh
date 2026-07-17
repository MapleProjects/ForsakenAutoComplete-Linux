#!/bin/bash
cd /home/maple/ForsakenAutoComplete-Linux
source venv/bin/activate

# Auto-detect XWayland display for tkinter (needs X11)
if [ -z "$DISPLAY" ]; then
    # Find the actual Xwayland display from running processes
    XDPY=$(pgrep -a Xwayland 2>/dev/null | grep -oP ':\d+' | head -1)
    if [ -n "$XDPY" ]; then
        export DISPLAY="$XDPY"
    elif [ -n "$WAYLAND_DISPLAY" ]; then
        export DISPLAY=":0"
    else
        # Try any wayland socket
        SOCKET=$(ls /run/user/"$(id -u)"/wayland-* 2>/dev/null | grep -v lock | head -1)
        if [ -n "$SOCKET" ]; then
            export WAYLAND_DISPLAY=$(basename "$SOCKET")
            export DISPLAY=":0"
        fi
    fi
fi

exec python3 flow_solver.py "$@"
