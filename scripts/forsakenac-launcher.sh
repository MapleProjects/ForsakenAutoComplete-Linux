#!/bin/bash
cd /opt/forsakenac

# Ensure ydotoold daemon is running (required for ydotool absolute positioning)
if ! pgrep -x ydotoold > /dev/null 2>&1; then
    ydotoold &
    sleep 0.3
fi

# Auto-detect XWayland display for tkinter (needs X11)
if [ -z "$DISPLAY" ]; then
    # Find the actual Xwayland display from running processes
    XDPY=$(pgrep -a Xwayland 2>/dev/null | grep -oP ':\d+' | head -1)
    if [ -n "$XDPY" ]; then
        export DISPLAY="$XDPY"
    elif [ -n "$WAYLAND_DISPLAY" ]; then
        export DISPLAY=":0"
    else
        SOCKET=$(ls /run/user/"$(id -u)"/wayland-* 2>/dev/null | grep -v lock | head -1)
        if [ -n "$SOCKET" ]; then
            export WAYLAND_DISPLAY=$(basename "$SOCKET")
            export DISPLAY=":0"
        fi
    fi
fi

exec /usr/bin/python3 flow_solver.py "$@"
