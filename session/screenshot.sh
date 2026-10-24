#!/bin/sh
# The whole screen, to a file and to the clipboard.
#
# The shell had no screenshot key of its own. Minecraft has F2 and nothing
# else did, so a browser or a terminal — every window that stacks above the
# game in Fork A — could not be captured at all.
#
# **Sway sees F2 before any window does, so binding it here takes it away from
# Minecraft.** That is deliberate rather than a cost: Minecraft is the
# fullscreen backdrop, so a grab of the whole output is the same picture the
# game would have saved, and every screenshot now lands in one directory
# instead of two. The one thing that is really gone is Minecraft's own F2 —
# and with it, the ability to *record* F2 on the Controls page, because the
# key never reaches the game to be captured. Bind something else there.
#
# One file, one command, like lock.sh: the Controls page rebinds the key by
# rewriting `bindsym`, and there is a single thing behind it to rebind.

set -u

say() {
	# Our own notification server draws this as an advancement toast. It may
	# not be up — the daemon might be restarting — and a screenshot that is
	# already on disk must not fail because nothing was there to announce it.
	command -v notify-send >/dev/null 2>&1 || return 0
	notify-send -a Screenshot "$@" >/dev/null 2>&1 || true
}

if ! command -v grim >/dev/null 2>&1; then
	say -u critical "Screenshot failed" "grim is not installed"
	exit 1
fi

dir=$(xdg-user-dir PICTURES 2>/dev/null) || dir=
[ -n "${dir:-}" ] || dir="$HOME/Pictures"
dir="$dir/Screenshots"

if ! mkdir -p "$dir" 2>/dev/null; then
	say -u critical "Screenshot failed" "cannot write to $dir"
	exit 1
fi

name="Screenshot_$(date +%Y-%m-%d_%H-%M-%S).png"
file="$dir/$name"

# No -o, so every output is composited into one image. This machine has a
# single monitor; asking for all of them is what "the whole screen" means on
# any number of them.
err=$(grim "$file" 2>&1) || {
	rm -f "$file"
	say -u critical "Screenshot failed" "${err:-grim exited non-zero}"
	exit 1
}

# The clipboard too, because the thing people do with a screenshot most often
# is paste it. wl-copy holds the selection by staying alive, so it is left
# running on purpose rather than waited for.
if command -v wl-copy >/dev/null 2>&1; then
	wl-copy --type image/png <"$file" >/dev/null 2>&1 &
fi

# -i is the notification's icon, and here it is the screenshot itself: the
# catalog's icon resolver takes an absolute path, so the toast shows a
# thumbnail of what was just taken.
say -i "$file" "Screenshot saved" "$name"
