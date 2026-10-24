#!/bin/sh
# Bring the Prism instance up to the spec in CLAUDE.md, and keep it there.
#
# Idempotent: run it again after editing mods.tsv, after a Java change, or
# when you are not sure what the instance is running. It settles four things
# and then hands off to install-mod.sh for the fifth.
#
# With no instance yet it makes one, out of the .mrpack: install-pack.py does
# what Prism's importer does, without the dialog that importer waits on. An
# instance that exists is never recreated, only brought up to date. The worlds
# it creates too, by copying the shipped templates into saves/ — never over a
# world that is already there. What it cannot do is sign in: that is Prism's
# window, and the one step a person has to take.

set -u

repo=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
. "$repo/session/prism/common.sh"

# --- 0. the instance itself ---------------------------------------------------
# $MCSHELL_PACK names a pack that was built already, which is how a package
# will ship one. From a checkout there is none, so build it: the mod's jar
# first, because the pack carries it.
if [ ! -f "$MCSHELL_INSTANCE/instance.cfg" ]; then
	pack=${MCSHELL_PACK:-}
	if [ -z "$pack" ]; then
		"$repo/mod/gradlew" -p "$repo/mod" --console=plain build || exit 1
		pack=$(python3 "$repo/session/prism/mrpack.py") || exit 1
	fi
	MCSHELL_INSTANCE="$MCSHELL_INSTANCE" python3 "$repo/session/prism/install-pack.py" "$pack" || exit 1
fi
require_instance

# --- helpers ----------------------------------------------------------------
# instance.cfg and options.txt are both flat key/value files, differing only
# in the separator. instance.cfg carries a [General] header and nothing else,
# so appending an unknown key at the end lands it in the right section.
set_key() {
	file=$1
	key=$2
	value=$3
	sep=$4
	if [ -f "$file" ] && grep -q "^$key$sep" "$file"; then
		# Values here are paths and numbers, never a pipe.
		sed -i "s|^$key$sep.*|$key$sep$value|" "$file"
	else
		printf '%s%s%s\n' "$key" "$sep" "$value" >>"$file"
	fi
}

cfg() { set_key "$MCSHELL_INSTANCE/instance.cfg" "$1" "$2" '='; }
opt() { set_key "$mc/options.txt" "$1" "$2" ':'; }

# --- 1. the JVM the instance runs on ----------------------------------------
# Pinned on the instance rather than left to Prism's global setting, which is
# shared with every other instance and one wrong click away from changing.
# This machine's default `java` is 26, which will not run 1.21.1 at all.
#
# 1G of heap, per CLAUDE.md. The world is 2x2 chunks of void; the heap is
# sized for a shell that runs for days beside real applications, not for a
# game that wants the machine to itself.
cfg OverrideJavaLocation true
cfg JavaPath /usr/lib/jvm/java-21-openjdk/bin/java
cfg OverrideMemory true
cfg MinMemAlloc 128
cfg MaxMemAlloc 1024

# Let the heap give back what it is not using. 1G stays the ceiling; what
# changes is the floor. At -Xms512m the JVM held 520MB of heap for the whole
# session while a full collection found 223MB alive. The free ratios make G1
# shrink toward what is live when it collects, and the periodic collection
# gives it a reason to while the game sits idle behind a window. Measure with
# session/probes/footprint.sh, not by reasoning — docs/testing/m8.md.
cfg OverrideJavaArgs true
cfg JvmArgs "-XX:G1PeriodicGCInterval=60000 -XX:MinHeapFreeRatio=10 -XX:MaxHeapFreeRatio=30"

# Prism's console window is a second window, and in the real session it would
# open on top of the shell during login. Keep it for failures only, where it
# is the difference between a diagnosis and a black screen.
cfg OverrideConsole true
cfg ShowConsole false
cfg ShowConsoleOnError true
cfg AutoCloseConsole true

# --- 2. client options ------------------------------------------------------
# Written into options.txt, which Minecraft rewrites wholesale when it exits.
# So these are defaults for the next start, not a lock: change one in-game and
# it sticks until this script runs again.
opt renderDistance 2
opt simulationDistance 5 # the vanilla minimum
opt maxFps 30

# The one that matters most, and the one nothing else can substitute for. A
# shell whose backdrop pauses itself the moment you click on a terminal is not
# a shell — the pause menu would be showing behind every window you ever open.
opt pauseOnLostFocus false

# Windowed, deliberately. session/layout.conf explains it at length: an
# XWayland fullscreen request makes Minecraft a fullscreen *container*, and
# sway then draws nothing else on the workspace, so applications would launch
# and be invisible. The layout fills the screen without it.
opt fullscreen false

# Silence, because this is a desktop. Minecraft's music starting unbidden
# twenty minutes into a work session is charming exactly once.
opt soundCategory_music 0.0

# --- 3. pinned performance mods ---------------------------------------------
# Verified against the sha512 recorded in mods.tsv, so a download that is
# truncated, redirected or replaced fails here rather than at the login
# screen. A file already in place with the right hash is left alone, which is
# what makes re-running this cheap.
mkdir -p "$mc/mods"
managed="$mc/mods/.mcshell-managed"
wanted=""

while IFS="$(printf '\t')" read -r name hash url; do
	case "${name:-}" in '' | '#'*) continue ;; esac
	wanted="$wanted$name
"
	target="$mc/mods/$name"
	if [ -f "$target" ] && [ "$(sha512sum <"$target" | cut -d' ' -f1)" = "$hash" ]; then
		continue
	fi
	echo "fetching $name"
	tmp="$target.part"
	if ! curl -fsSL --retry 3 -o "$tmp" -- "$url"; then
		rm -f "$tmp"
		echo "download failed: $url" >&2
		exit 1
	fi
	got=$(sha512sum <"$tmp" | cut -d' ' -f1)
	if [ "$got" != "$hash" ]; then
		rm -f "$tmp"
		echo "sha512 mismatch for $name" >&2
		echo "  expected $hash" >&2
		echo "  got      $got" >&2
		exit 1
	fi
	mv -- "$tmp" "$target"
done <"$repo/session/prism/mods.tsv"

# Retire what this script installed on an earlier run and no longer wants —
# a version bump changes the filename, and the old jar left beside the new one
# is a duplicate mod id, which Fabric refuses to start with. Only files we
# recorded are eligible, so anything you added to the instance yourself stays.
if [ -f "$managed" ]; then
	while read -r old; do
		[ -n "${old:-}" ] || continue
		case "$wanted" in *"$old"*) continue ;; esac
		echo "removing superseded $old"
		rm -f "$mc/mods/$old"
	done <"$managed"
fi
printf '%s' "$wanted" >"$managed"

# --- 4. the mod itself ------------------------------------------------------
"$repo/session/prism/install-mod.sh" || exit 1

# --- 5. the worlds -----------------------------------------------------------
"$repo/session/prism/seed-worlds.sh"

# And a missing one is worth saying out loud now rather than as a launcher
# error later: session/prism/launch.sh joins it by name.
if [ ! -d "$mc/saves/$MCSHELL_WORLD" ]; then
	echo >&2
	echo "warning: no world named '$MCSHELL_WORLD' in $mc/saves/" >&2
	echo "the instance will launch to the title screen." >&2
fi

echo "instance ready: $MCSHELL_INSTANCE"
