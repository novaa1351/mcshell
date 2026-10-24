#!/usr/bin/env python3
"""A native Wayland window that draws with OpenGL, and counts its frames.

GTK 4's default renderer is OpenGL, so this is what the session's own GTK apps
are, seen from the compositor. It redraws every frame until SIGTERM and then
prints how many it drew, in glxgears' words so one parser reads both; the exit
status is 124 if it drew any, timeout's own code for "still running", and 1
if it drew none. A compositor that drops it shows as a different status.

    timeout 6 session/probes/gtk-frames.py       # used by xwayland-gl.sh
"""

import signal
import sys

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

drawn = 0


def report() -> bool:
    print(f"{drawn} frames in 5.0 seconds", flush=True)
    sys.exit(124 if drawn else 1)


def tick(widget, clock) -> bool:
    global drawn
    drawn += 1
    widget.queue_draw()
    return GLib.SOURCE_CONTINUE


def activate(app: Gtk.Application) -> None:
    win = Gtk.ApplicationWindow(application=app, title="probe")
    area = Gtk.DrawingArea()
    area.set_draw_func(lambda *_: None)
    area.add_tick_callback(tick)
    win.set_child(area)
    win.present()


app = Gtk.Application(application_id="dev.mcshell.probe")
app.connect("activate", activate)
GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, report)
sys.exit(app.run([]) or 1)
