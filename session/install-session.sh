#!/bin/sh
# Install the MCShell session: systemd user units, and the login screen's entry.
#
# Idempotent, and safe to re-run after pulling. Everything it writes is derived
# from a template in this repo, so the repo stays the source of truth and a
# moved checkout is one re-run away from correct.
#
#   install-session.sh              units, then the session entry (asks for sudo)
#   install-session.sh --user-only  units only; prints the root command
#
# The session entry is the one root-owned file, because display managers read
# /usr/share/wayland-sessions and nothing under $HOME. That directory is the
# freedesktop convention rather than GDM's: SDDM, LightDM and greetd's
# greeters list it too, so there is nothing per display manager to write.
# Only GDM has been tried. It is also the file that makes MCShell *a second
# entry* rather than a replacement: every other session stays in the picker
# exactly as it is.

set -u

repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
units="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
entry=/usr/share/wayland-sessions/mcshell.desktop

user_only=0
[ "${1:-}" = "--user-only" ] && user_only=1

# --- what has to exist before any of this is worth installing ---------------
missing=0
check() {
	if [ ! -e "$1" ]; then
		echo "missing: $1 — $2" >&2
		missing=1
	fi
}
check "$repo/daemon/.venv/bin/mcshelld" "cd daemon && uv venv && uv pip install -e ."
check /usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1 "pacman -S polkit-gnome"
check /usr/bin/swaylock "pacman -S swaylock"
check /usr/bin/hyprlock "pacman -S hyprlock"
check /usr/lib/libgtk4-layer-shell.so "pacman -S gtk4-layer-shell"
# Not checked, deliberately: ImageMagick is only the lock screen's third
# route. The first two draw Minecraft's own screen out of the client jar and
# need nothing but python3, and the last is bare swaylock. All four lock.
check /usr/bin/sway "pacman -S sway"
# Any terminal will do: the session runs $TERMINAL and falls back to foot.
# Asked by name on PATH, not by package, so another distro's foot counts.
term=${TERMINAL:-foot}
if ! command -v "${term%% *}" >/dev/null 2>&1 && ! command -v foot >/dev/null 2>&1; then
	echo "missing: a terminal — set TERMINAL in ~/.config/environment.d, or pacman -S foot" >&2
	missing=1
fi
check /usr/bin/prismlauncher "pacman -S prismlauncher"
[ "$missing" -eq 1 ] && exit 1

# --- systemd user units ------------------------------------------------------
# @REPO@ rather than %h: the checkout is not required to live in the home
# directory, and a unit that only works in one place is a trap for the day it
# moves.
mkdir -p "$units"
render() {
	sed "s|@REPO@|$repo|g" "$repo/session/systemd/$1.in" >"$units/$1"
	echo "  $units/$1"
}
echo "units:"
render mcshelld.service
render mcshell-client.service
cp "$repo/session/systemd/mcshell-session.target" "$units/mcshell-session.target"
echo "  $units/mcshell-session.target"
systemctl --user daemon-reload

# --- the session entry -------------------------------------------------------
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
sed "s|@REPO@|$repo|g" "$repo/session/mcshell.desktop.in" >"$tmp"

if [ -f "$entry" ] && cmp -s "$tmp" "$entry"; then
	echo "session entry: already current ($entry)"
	exit 0
fi

if [ "$user_only" -eq 1 ]; then
	echo
	echo "session entry not installed yet: $entry"
	echo "re-run without --user-only to install it; it will ask for sudo."
	exit 0
fi

echo "session entry: installing $entry (sudo)"
sudo install -Dm644 "$tmp" "$entry" || exit 1
echo "done — MCShell is now in the login screen's session list"
