#!/bin/sh
# The volume and mute keys, and the one thing that tells the shell they were
# pressed.
#
# One file behind the keys for the same reason `lock.sh` and `screenshot.sh`
# are one file: the Controls page rebinds these by rewriting `bindsym`, and
# there should be a single thing behind each key to rebind.
#
# `wpctl` first and unconditionally, so this is still the safety rail it was:
# the volume changes with the daemon dead, with Minecraft dead, and over the
# lock screen. Only the popup is lost without a daemon, and the popup is the
# daemon's anyway.
#
# --- why it tells the daemon at all ---
#
# The volume popup is drawn from the daemon's `pactl subscribe` feed, not from
# the keypress, so that `wpctl` from the command bar, our own slider, a headset
# wheel and this key all draw the same bar. That is still true and this does
# not change it.
#
# What it cannot cover is a press that changes nothing. Measured: PipeWire
# emits **no event at all** for a write that lands on the value already there —
# `5%-` at zero, `5%+` at a hundred, mute when already muted are each zero sink
# events, where a real change is one. So at the extremes the subscription has
# nothing to react to, the bar never appears, and the key reads as broken
# rather than as already-there. Only the thing that pressed the key knows it
# happened, so it says so.
#
# Sent every press rather than only on the no-op ones: finding out whether the
# value moved costs two `wpctl get-volume` calls at 16ms each, which is more
# than the 7ms of just saying so. The daemon debounces, and drawing the same
# bar twice is what it already does for any change.

set -u

sock="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/mcshell.sock"

# Best effort, always. A daemon that is not running, a socket that is not
# there, and a machine with neither tool are all "no popup", never "no volume".
tell_the_shell() {
	[ -S "$sock" ] || return 0
	if command -v socat >/dev/null 2>&1; then
		printf '{"t":"osd_volume"}\n' | socat - "UNIX-CONNECT:$sock" >/dev/null 2>&1 || true
	elif command -v python3 >/dev/null 2>&1; then
		python3 -c 'import socket,sys
s = socket.socket(socket.AF_UNIX)
try:
    s.connect(sys.argv[1]); s.sendall(b"{\"t\":\"osd_volume\"}\n")
finally:
    s.close()' "$sock" >/dev/null 2>&1 || true
	fi
}

case "${1:-}" in
up)
	# wpctl's -l caps at 100%. Above that is clipping, not loudness, and
	# pactl cannot express the cap at all.
	wpctl set-volume -l 1.0 @DEFAULT_AUDIO_SINK@ 5%+
	tell_the_shell
	;;
down)
	wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-
	tell_the_shell
	;;
mute)
	wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle
	tell_the_shell
	;;
micmute)
	# No popup: the bar reads the *sink*, and drawing the speaker's level
	# because the microphone was muted would be a lie about which one moved.
	wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle
	;;
*)
	echo "usage: $(basename -- "$0") up|down|mute|micmute" >&2
	exit 2
	;;
esac
