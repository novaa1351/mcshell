#!/bin/sh
# Launch the shell's Minecraft client, joining the shell world directly.
#
# This is the command the M7 systemd user unit will run, so it lives here
# rather than in the unit: the unit should be a wrapper thin enough to be
# uninteresting, and this is a thing you can also run by hand from a terminal
# when the session is misbehaving.
#
# Prism stays in the foreground as the client's parent for as long as
# Minecraft runs, which is what a systemd service wants.
#
#   launch.sh              online if the network answers, offline if not
#   launch.sh --offline    no Microsoft round trip, whatever the network says
#   launch.sh --online     let Prism try regardless
#
# Offline is decided *here*, before Prism starts, by online.sh. Left to Prism,
# a machine with no network gets a full-screen "Choose your offline mode
# player name" window in 0.13s — underneath the boot screen, which covers every
# window, until that screen's 90s timeout. Everywhere else a failed sign-in
# means no game; here it means a desktop that looks hung.
#
# Offline costs nothing a shell cares about. Measured in the 1.21.1 bytecode:
# a singleplayer world loads its host from the `Player` tag in level.dat,
# matched by name (`IntegratedServer.isHost`, `PlayerManager.loadPlayerData`),
# not from the per-UUID file — so the offline UUID still finds the same
# inventory, in the same place. What is lost is the skin.

set -u

repo=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
. "$repo/session/prism/common.sh"
require_instance

sock="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/mcshell.sock"

# One line to the daemon, best effort, like volume.sh's: the game has to start
# with the daemon dead, so nothing here may wait on it or fail because of it.
tell_the_shell() {
	[ -S "$sock" ] || return 0
	if command -v socat >/dev/null 2>&1; then
		printf '%s\n' "$1" | socat - "UNIX-CONNECT:$sock" >/dev/null 2>&1 || true
	elif command -v python3 >/dev/null 2>&1; then
		python3 -c 'import socket,sys
s = socket.socket(socket.AF_UNIX)
try:
    s.connect(sys.argv[1]); s.sendall(sys.argv[2].encode() + b"\n")
finally:
    s.close()' "$sock" "$1" >/dev/null 2>&1 || true
	fi
}

# The name an offline session plays as: the signed-in account's own, which is
# what Prism's prompt offers pre-filled, so offline looks like online with no
# skin. Read from Prism's account list, the active account first. Not the
# tokens — only `profile.name`.
account_name() {
	python3 - "${XDG_DATA_HOME:-$HOME/.local/share}/PrismLauncher/accounts.json" <<'PY' 2>/dev/null
import json, sys
accounts = json.load(open(sys.argv[1])).get("accounts", [])
accounts.sort(key=lambda a: not a.get("active"))
for a in accounts:
    name = (a.get("profile") or {}).get("name")
    if name:
        print(name)
        break
PY
}

# Minecraft chooses its windowing backend at startup, and GLFW falls back to
# Wayland when there is no DISPLAY. That client sets no app_id and has no
# window_class, so nothing in the shell can match it — layout.conf cannot pin it
# to the screen and the daemon skips it as unaddressable. The symptom is a small
# Minecraft floating in the middle of a desktop that otherwise looks fine, which
# is a long way from the cause.
#
# A warning rather than a refusal: a client that says why it will misbehave
# beats no client at all, and refusing here would only restart-loop the unit.
if [ -z "${DISPLAY:-}" ]; then
	echo "warning: DISPLAY is unset, so Minecraft will run as a native Wayland" >&2
	echo "         client with no app_id, and the shell will not be able to see" >&2
	echo "         or place its own backdrop. sway.conf imports DISPLAY into the" >&2
	echo "         user manager for exactly this reason." >&2
fi

offline=
for arg in "$@"; do
	case "$arg" in
	--offline) offline=1 ;;
	--online) offline=0 ;;
	*)
		echo "usage: $(basename -- "$0") [--offline | --online]" >&2
		exit 2
		;;
	esac
done

if [ -z "$offline" ]; then
	if "$repo/session/prism/online.sh"; then
		offline=0
	else
		offline=1
		echo "no network: launching offline" >&2
	fi
fi

if [ "$offline" -eq 1 ]; then
	: "${MCSHELL_OFFLINE_NAME:=$(account_name)}"
	: "${MCSHELL_OFFLINE_NAME:=Player}"
	# So the boot screen can say why, rather than leave somebody wondering
	# whether a quieter login is a broken one.
	tell_the_shell '{"t":"launch_mode","offline":true}'
fi

# --world joins the world at launch instead of stopping at the title screen.
# Without it the shell boots to a main menu, which is a desktop nobody has
# logged into yet.
set -- --launch "$MCSHELL_INSTANCE_NAME" --world "$MCSHELL_WORLD"
[ "$offline" -eq 1 ] && set -- "$@" --offline "$MCSHELL_OFFLINE_NAME"

# What is actually running, which is not always what is chosen: the settings
# page can pick another world for the next start while this one is still up.
printf '%s\n' "$MCSHELL_WORLD" > "${XDG_RUNTIME_DIR:-/tmp}/mcshell-world.running" 2>/dev/null || true

# Two malloc arenas instead of glibc's default of up to eight per core. Java
# objects never touch malloc; the JIT, the GL driver and LWJGL do, and a
# thread that contends gets an arena of its own that rarely shrinks: measured
# at 16 arenas holding 225MB. The cost, if any, is those threads queueing on
# a lock — speed, never correctness. Here rather than in Prism's instance
# settings, because Qt's INI format strips the quotes out of the JSON Prism
# keeps them in and the variable silently never arrives. Prism passes its own
# environment on to the game. Set it yourself to override.
export MALLOC_ARENA_MAX="${MALLOC_ARENA_MAX:-2}"

exec prismlauncher "$@"
