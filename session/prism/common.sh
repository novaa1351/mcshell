# shellcheck shell=sh
# Sourced by the scripts in this directory. Not executable on its own.
#
# Where the instance is. Prism keeps instances under its data directory, one
# directory per instance, named by the instance name — so the name is also the
# path, and the launcher takes the same string on the command line.
#
# Both are overridable by environment, so a second instance can be built and
# tested without editing anything: MCSHELL_INSTANCE_NAME picks a different
# instance in the usual place, MCSHELL_INSTANCE points at a directory anywhere.

: "${MCSHELL_INSTANCE_NAME:=MCShell}"
: "${MCSHELL_INSTANCE:=$HOME/.local/share/PrismLauncher/instances/$MCSHELL_INSTANCE_NAME}"

# Which world. An environment override wins; otherwise the one chosen on the
# shell's settings page, which mcshelld writes to ~/.config/mcshell/world. Read
# here rather than asked of the daemon, because the game has to start with the
# daemon dead. A choice that names no world falls back to Tutorial World — the
# default, and one of the shipped templates — loudly: a desktop that will not
# start because a folder was renamed would be a bad trade.
_default="Tutorial World"
if [ -z "${MCSHELL_WORLD:-}" ]; then
	_choice="${XDG_CONFIG_HOME:-$HOME/.config}/mcshell/world"
	if [ -r "$_choice" ]; then
		IFS= read -r MCSHELL_WORLD < "$_choice" || true
		case "$MCSHELL_WORLD" in
		"" | */*) MCSHELL_WORLD= ;;
		esac
		if [ -n "$MCSHELL_WORLD" ] && [ ! -f "$MCSHELL_INSTANCE/minecraft/saves/$MCSHELL_WORLD/level.dat" ]; then
			# Only worth saying when the fallback is a different world. On a
			# machine being set up, the choice is the default and neither
			# exists yet — "not there; opening it anyway" is noise.
			[ "$MCSHELL_WORLD" = "$_default" ] ||
				echo "warning: the chosen world '$MCSHELL_WORLD' is not there; opening $_default" >&2
			MCSHELL_WORLD=
		fi
	fi
	unset _choice
fi
: "${MCSHELL_WORLD:=$_default}"
unset _default

# The .minecraft equivalent. Prism calls it "minecraft"; mods, options.txt and
# saves all live under it.
# shellcheck disable=SC2034  # read by the scripts that source this
mc="$MCSHELL_INSTANCE/minecraft"

require_instance() {
	if [ ! -f "$MCSHELL_INSTANCE/instance.cfg" ]; then
		echo "no Prism instance at $MCSHELL_INSTANCE" >&2
		echo "create it in Prism (Minecraft 1.21.1, Fabric) and name it $MCSHELL_INSTANCE_NAME" >&2
		exit 1
	fi
}
