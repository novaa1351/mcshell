#!/bin/sh
# What the shell can actually see. Run it from a terminal inside the session —
# $mod+Shift+Return opens one — when something looks wrong and it is not
# obvious which layer is at fault.
#
# It answers the questions that have actually come up, in the order they cost
# time: is the compositor the one we think, does Minecraft have an identity
# anything can match, are the units alive, and did the environment get through.

set -u

repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

section() { printf '\n== %s ==\n' "$1"; }

section "compositor"
if [ -z "${SWAYSOCK:-}" ]; then
	echo "SWAYSOCK unset — this is not a sway session, or not the shell's"
else
	echo "SWAYSOCK   $SWAYSOCK"
	swaymsg -t get_version 2>/dev/null | head -1
fi
echo "DISPLAY    ${DISPLAY:-(unset)}"
echo "WAYLAND_DISPLAY ${WAYLAND_DISPLAY:-(unset)}"

# DISPLAY unset means Minecraft came up as a native Wayland client with no
# app_id, which nothing in the shell can match. It is the first thing to rule
# out, because every downstream symptom looks like a different bug.
[ -z "${DISPLAY:-}" ] && echo "  !! DISPLAY is unset — see 'windows' below; the backdrop will be unmatched"

section "windows sway knows about"
swaymsg -t get_tree 2>/dev/null | python3 -c '
import json, sys


def walk(node, out):
    for child in node.get("nodes", []) + node.get("floating_nodes", []):
        if not child.get("nodes") and not child.get("floating_nodes"):
            props = child.get("window_properties") or {}
            out.append(
                (
                    child.get("id"),
                    child.get("app_id"),
                    props.get("class"),
                    child.get("shell"),
                    child.get("rect"),
                )
            )
        walk(child, out)


rows = []
walk(json.load(sys.stdin), rows)
if not rows:
    print("  (none)")
for con_id, app_id, cls, shell, rect in rows:
    ident = app_id or cls
    mark = "" if ident else "   <-- NO IDENTITY: nothing can match this window"
    print(
        "  %-6s app_id=%-28r class=%-22r %s %sx%s+%s+%s%s"
        % (
            con_id,
            app_id,
            cls,
            shell,
            rect["width"],
            rect["height"],
            rect["x"],
            rect["y"],
            mark,
        )
    )
' 2>/dev/null || echo "  (could not read the tree)"

section "units"
systemctl --user --no-pager --plain list-units 'mcshell*' 2>/dev/null | sed -n '1,6p'
echo "last 5 lines of each:"
journalctl --user -u mcshelld -n 5 --no-pager 2>/dev/null | tail -5
journalctl --user -u mcshell-client -n 5 --no-pager 2>/dev/null | tail -5

section "mod jar"
# The question this answers: am I looking at the code I just built?
#
# It is here because it has cost a whole test round. A stale jar does not look
# like a stale jar — it looks like a change that silently did nothing, and
# every symptom it produces is a plausible bug somewhere else. The give-away is
# that anything outside the jar (a sway binding, a daemon change) works while
# everything inside it does not, and that is a hard pattern to notice from the
# inside.
#
# Only the Prism instance can go stale. The dev client compiles from source on
# every launch, so if $client is run-client.sh this section has nothing to say.

# Sets MCSHELL_INSTANCE and mc. Deliberately not require_instance — a missing
# instance is a thing to report, not a reason to stop the whole diagnosis.
. "$repo/session/prism/common.sh"

pick_jar() {
	# The release jar, skipping the ones gradle leaves beside it.
	found=""
	for f in $1; do
		case "$f" in
		*-sources.jar | *-dev.jar | *-dev-shadow.jar) continue ;;
		*'*'*) continue ;;
		esac
		[ -f "$f" ] && found="$f"
	done
	printf '%s' "$found"
}

built=$(pick_jar "$repo/mod/build/libs/mcshell-*.jar")
installed=$(pick_jar "$mc/mods/mcshell-*.jar")

if [ ! -d "$MCSHELL_INSTANCE" ]; then
	echo "  no Prism instance at $MCSHELL_INSTANCE"
elif [ -z "$installed" ]; then
	echo "  !! no mcshell jar installed in $mc/mods"
	echo "     run session/prism/install-mod.sh"
elif [ -z "$built" ]; then
	echo "  installed $(basename -- "$installed")  ($(date -r "$installed" '+%F %T'))"
	echo "  (nothing built in mod/build/libs to compare against)"
else
	echo "  built     $(date -r "$built" '+%F %T')  $built"
	echo "  installed $(date -r "$installed" '+%F %T')  $installed"
	if [ "$(sha256sum <"$built" | cut -d" " -f1)" = "$(sha256sum <"$installed" | cut -d" " -f1)" ]; then
		echo "  same jar."
	else
		echo "  !! DIFFERENT — the instance is not running what was last built"
		echo "     run session/prism/install-mod.sh, then restart the client"
	fi

	# Source newer than the jar. This is the case the checksum above cannot
	# see: edit the mod, never build, and both jars agree perfectly on the old
	# code. A hint rather than a finding, because gradle leaves the jar alone
	# when a change cannot alter the bytecode — editing only a comment trips
	# this and means nothing.
	newer=$(find "$repo/mod/src" -newer "$built" -type f -print -quit 2>/dev/null)
	[ -n "$newer" ] && echo "  note: mod/src has files newer than the jar (e.g. $(basename -- "$newer"))" &&
		echo "        harmless if you only changed comments; otherwise build"
fi

# And the sharpest version of the question: a jar installed after the client
# started is a jar the client has never read. This is exactly the case that
# reads as "my change did nothing" while the file on disk is perfectly correct.
if [ -n "${installed:-}" ] && [ -f "${installed:-}" ]; then
	pid=$(pgrep -f "instances/$MCSHELL_INSTANCE_NAME" 2>/dev/null | head -1)
	if [ -n "$pid" ]; then
		started=$(ps -o lstart= -p "$pid" 2>/dev/null)
		echo "  client pid $pid started $started"
		if [ -n "$started" ] && [ "$(date -d "$started" +%s 2>/dev/null || echo 0)" -lt \
			"$(date -r "$installed" +%s)" ]; then
			echo "  !! the running client started BEFORE this jar was installed"
			echo "     it is still running the old one — restart it"
			echo "     (Prism will not start a second copy: quit the game first)"
		fi
	else
		echo "  (no running client matched)"
	fi
fi

section "daemon"
if [ -S "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/mcshell.sock" ]; then
	"$repo/daemon/tools/mcsh" windows 2>&1 | head -12
else
	echo "  no socket — the daemon is not listening"
fi

section "environment the units were given"
systemctl --user show-environment 2>/dev/null |
	grep -E '^(DISPLAY|WAYLAND_DISPLAY|SWAYSOCK|XDG_CURRENT_DESKTOP|XDG_SESSION_DESKTOP)=' ||
	echo "  (none imported)"

printf '\n'
