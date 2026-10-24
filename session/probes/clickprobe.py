#!/usr/bin/env python3
"""A window that reports the pointer events it actually receives.

    session/probes/clickprobe.py x11        # an XWayland client
    session/probes/clickprobe.py wayland    # a native Wayland client

Open one of each and you can tell the two apart, which matters more than it
sounds: they fail differently. An X pointer grab is server-wide, so a stranded
one takes the clicks of every *X* client while leaving native Wayland ones
untouched. A fix verified against the wrong one of these passes while the bug
is still there — that is exactly how the cursor bug survived three attempts.

The counters are drawn in the window and also written to a state file, so a
test script can read them without a person watching:

    session/probes/clickprobe.py x11 &
    swaymsg 'seat - cursor set 960 540'
    swaymsg 'seat - cursor press button1'; swaymsg 'seat - cursor release button1'
    cat "${XDG_RUNTIME_DIR:-/tmp}/mcshell-clickprobe-x11"

Motion without clicks is the signature to look for. It means events are
reaching the screen but the buttons are going somewhere else.
"""

import os
import sys

backend = sys.argv[1] if len(sys.argv) > 1 else "x11"
if backend not in ("x11", "wayland"):
    sys.exit("usage: clickprobe.py [x11|wayland]")

# Before gi, or GTK has already chosen for us.
os.environ["GDK_BACKEND"] = backend

import gi  # noqa: E402

# Both, explicitly: importing Gdk without a version pinned resolves it to 4.0
# and then Gtk 3.0 cannot load.
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

STATE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
                     f"mcshell-clickprobe-{backend}")

clicks = 0
motion = 0
label = Gtk.Label()


def refresh():
    label.set_markup(
        f"<span size='48000'><b>{backend}</b>\n"
        f"clicks {clicks}\nmotion {motion}</span>")
    with open(STATE, "w") as f:
        f.write(f"{clicks} {motion}\n")


def on_button(_w, e):
    global clicks
    # Press only. GTK also reports 2BUTTON_PRESS and 3BUTTON_PRESS for the same
    # physical clicks, and three fast clicks would otherwise count as five.
    if e.type != Gdk.EventType.BUTTON_PRESS:
        return True
    clicks += 1
    print(f"click {clicks}", flush=True)
    refresh()
    return True


def on_motion(_w, _e):
    global motion
    motion += 1
    refresh()
    return True


win = Gtk.Window(title=f"clickprobe {backend}")
win.set_default_size(900, 600)
win.add(label)
win.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
win.connect("button-press-event", on_button)
win.connect("motion-notify-event", on_motion)
win.connect("destroy", Gtk.main_quit)
win.show_all()
refresh()
print(f"clickprobe {backend}: counters at {STATE}", flush=True)
Gtk.main()
