#!/bin/sh
# Resize windows to the whole output, and put them at 0,0.
#
# With no arguments, the focused window. With arguments, each is a sway
# criteria string, and one that matches nothing is a no-op — which is how
# raise-mc.sh gets to try both of Minecraft's identities for the price of one.
#
# It resizes twice with a pause between, and both halves of that are
# load-bearing. The first resize lands a few pixels short — 1276x716 on a
# 1280x720 output — because sway works `100ppt` out against the size the
# client has actually committed to, which is still the old one. The second
# resize, against the committed size, is exact, and every one after it is a
# no-op. Measured at four resolutions, and it holds for a window that has been
# sitting at the wrong size for minutes as much as for one still mapping: it
# is the client's commit that has to happen in between, not any settling.
#
# So this cannot be a sway command, and it cannot be a `for_window` line.
# Two commands in one message never work (sway takes the whole message against
# one snapshot), and neither do two messages sent back to back.

set -u

fill='resize set 100ppt 100ppt, move position 0 0'

pass() {
	if [ "$#" -eq 0 ]; then
		swaymsg "$fill" >/dev/null 2>&1 || true
		return
	fi
	for criteria in "$@"; do
		swaymsg "[$criteria] $fill" >/dev/null 2>&1 || true
	done
}

pass "$@"
sleep 0.15
pass "$@"
