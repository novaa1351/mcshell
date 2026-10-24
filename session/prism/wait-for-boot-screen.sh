#!/bin/sh
# Hold the game back until the boot screen is actually on the screen.
#
# The boot screen is a layer-shell surface above every ordinary window, so it
# covers Prism's launcher — but it cannot cover a window that appeared before
# it existed, and that is a race it loses from a standing start. systemd starts
# this unit and the daemon in the same millisecond; the daemon hands the first
# frame to the overlay 16ms later, but the overlay is a Python interpreter, an
# LD_PRELOAD re-exec and a GTK import away from painting anything. Measured in
# a nested compositor: about 0.9s warm and **2.9s on the first run**, which is
# what a login always is. Prism is compiled Qt and wins comfortably.
#
# So rather than make the shell faster than Prism — which was tried, and which
# only ever narrows a race — the game waits. `overlay.py` touches the marker
# from its draw handler, so it means the frame reached the compositor and not
# merely that one was composed.
#
# This never fails the unit. If the boot screen is not coming — no layer-shell,
# no client jar, an overlay that died — waiting forever would trade a cosmetic
# problem for a session that never starts. It gives up and lets the game go.

set -u

marker="${XDG_RUNTIME_DIR:-/tmp}/mcshell-boot.drawn"

# Long enough for a cold first paint with room to spare, short enough that a
# boot screen which is never coming costs a few seconds once, at a point in the
# login where several other things are already being waited on. Counted in
# tenths, which is the polling interval.
limit=80
waited=0

while [ ! -e "$marker" ]; do
	if [ "$waited" -ge "$limit" ]; then
		echo "boot screen did not appear in $((limit / 10))s; starting the game anyway" >&2
		exit 0
	fi
	sleep 0.1
	waited=$((waited + 1))
done

exit 0
